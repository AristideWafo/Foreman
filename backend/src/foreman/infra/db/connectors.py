"""Statut des connecteurs en PostgreSQL (table `connectors`, migration 0008).

Chaque écriture et sa ligne d'audit (`integration.<action>`) partagent la même transaction.
L'audit ne reçoit que le nom du connecteur et des jetons, jamais une valeur.
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from foreman.core.connector_state import (
    ConnectorState,
    ConnectorStatus,
    CredentialAction,
)
from foreman.core.gateway.port import ProbeVerdict, RightVerdict
from foreman.core.store import StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

_C = t.connectors
_VERDICTS: frozenset[str] = frozenset({"ok", "missing", "excess"})


def _column(token: str) -> str:
    return "write_secret_ref" if token == "write" else "read_secret_ref"  # noqa: S105


class PostgresConnectorStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def states(self) -> Mapping[str, ConnectorState]:
        try:
            async with self._engine.connect() as conn:
                rows = (await conn.execute(sa.select(_C))).all()
        except SQLAlchemyError as exc:
            log_failure("connectors.states", exc)
            raise StoreError("stockage indisponible") from None
        return {
            r.provider: ConnectorState(r.status, _rights(r.verified_scopes), r.last_probe_at)
            for r in rows
        }

    async def save_probe(
        self,
        connector: str,
        declared: Mapping[str, list[str]],
        status: ConnectorStatus,
        rights: tuple[RightVerdict, ...],
        actor: UUID,
    ) -> None:
        verified = {
            "rights": [{"token": r.token, "right": r.right, "verdict": r.verdict} for r in rights]
        }
        await self._write(
            connector,
            declared,
            actor,
            "credential.test",
            {"statut": status},
            {"status": status, "verified_scopes": verified, "last_probe_at": datetime.now(UTC)},
        )

    async def save_change(
        self,
        connector: str,
        declared: Mapping[str, list[str]],
        action: CredentialAction,
        secret_refs: Mapping[str, str | None],
        actor: UUID,
    ) -> None:
        values: dict[str, Any] = {_column(k): v for k, v in secret_refs.items()}
        if action == "credential.set":  # nouveau jeton : droits à re-prouver par une sonde
            values |= {"status": "incomplete", "verified_scopes": {}, "last_probe_at": None}
        elif action == "credential.revoke":
            values |= {"status": "revoked", "verified_scopes": {}}
        await self._write(
            connector, declared, actor, action, {"jetons": sorted(secret_refs)}, values
        )

    async def _write(
        self,
        connector: str,
        declared: Mapping[str, list[str]],
        actor: UUID,
        action: str,
        detail: dict[str, Any],
        values: dict[str, Any],
    ) -> None:
        base = {"name": connector, "declared_scopes": dict(declared)}
        stmt = insert(_C).values(provider=connector, **base, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[_C.c.provider], set_={**base, **values})
        try:
            async with self._engine.begin() as conn:
                await conn.execute(stmt)
                await _audit(conn, actor, action, {"connecteur": connector, **detail})
        except SQLAlchemyError as exc:
            log_failure(f"connectors.{action}", exc)
            raise StoreError("stockage indisponible") from None


async def _audit(conn: AsyncConnection, actor: UUID, action: str, params: dict[str, Any]) -> None:
    await conn.execute(
        sa.insert(t.audit_events).values(
            actor_kind="user",
            actor_id=actor,
            tool=f"integration.{action}",
            decision="allow",
            params_redacted=params,
        )
    )


def _rights(verified: Any) -> tuple[RightVerdict, ...]:
    raw = verified.get("rights", []) if isinstance(verified, dict) else []
    return tuple(
        RightVerdict(r["token"], r["right"], cast(ProbeVerdict, r["verdict"]))
        for r in raw
        if r.get("verdict") in _VERDICTS
    )
