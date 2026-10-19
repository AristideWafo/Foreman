"""Journal d'audit en PostgreSQL (append-only : un déclencheur refuse UPDATE, DELETE, TRUNCATE)."""

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.store import AuditEntry, StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure


def audit_values(entry: AuditEntry) -> dict[str, Any]:
    return {
        "project_id": entry.project_id,
        "plan_id": entry.plan_id,
        "execution_id": entry.execution_id,
        "step_seq": entry.step_seq,
        "plan_hash": entry.plan_hash,
        "actor_kind": entry.actor_kind,
        "actor": entry.actor,
        "tool": entry.tool,
        "tool_class": entry.tool_class,
        "decision": entry.decision,
        "rule_id": entry.rule_id,
        "params_redacted": None if entry.params_redacted is None else dict(entry.params_redacted),
        "result_redacted": None if entry.result_redacted is None else dict(entry.result_redacted),
        "duration_ms": entry.duration_ms,
    }


class PostgresAuditLog:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(self, entry: AuditEntry) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(sa.insert(t.audit_events).values(**audit_values(entry)))
        except SQLAlchemyError as exc:
            log_failure("audit.append", exc)
            raise StoreError("audit invalide") from None

    async def list_for_project(
        self, project_id: UUID, limit: int = 200, *, execution_id: UUID | None = None
    ) -> list[AuditEntry]:
        statement = sa.select(*t.audit_events.c).where(t.audit_events.c.project_id == project_id)
        if execution_id is not None:
            statement = statement.where(t.audit_events.c.execution_id == execution_id)
        statement = statement.order_by(t.audit_events.c.id).limit(limit)
        try:
            async with self._engine.connect() as conn:
                rows = (await conn.execute(statement)).all()
        except SQLAlchemyError as exc:
            log_failure("audit.list", exc)
            raise StoreError("stockage indisponible") from None
        return [
            AuditEntry(
                actor_kind=r.actor_kind,
                project_id=r.project_id,
                plan_id=r.plan_id,
                execution_id=r.execution_id,
                step_seq=r.step_seq,
                plan_hash=r.plan_hash,
                actor=r.actor,
                tool=r.tool,
                tool_class=r.tool_class,
                decision=r.decision,
                rule_id=r.rule_id,
                params_redacted=r.params_redacted,
                result_redacted=r.result_redacted,
                duration_ms=r.duration_ms,
            )
            for r in rows
        ]
