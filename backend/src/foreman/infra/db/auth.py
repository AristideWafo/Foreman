"""Sessions et connexions en PostgreSQL (condensats uniquement)."""

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.accounts import rank
from foreman.core.auth import SESSION_TTL, Credentials, SessionInfo
from foreman.core.store import StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

_S = t.sessions
_U = t.users
_M = t.memberships


class PostgresAuthStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def credentials(self, email: str) -> Credentials | None:
        query = sa.select(_U.c.id, _U.c.password_hash, _U.c.disabled_at).where(
            sa.func.lower(_U.c.email) == email.lower()
        )
        row = await self._run("auth.credentials", query)
        return (
            None
            if row is None
            else Credentials(row.id, row.password_hash, row.disabled_at is not None)
        )

    async def open_session(
        self, id_hash: str, csrf_hash: str, user_id: UUID, now: datetime
    ) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(sa.delete(_S).where(_S.c.expires_at <= now))  # purge paresseuse
                await conn.execute(
                    sa.insert(_S).values(
                        id_hash=id_hash,
                        csrf_hash=csrf_hash,
                        user_id=user_id,
                        expires_at=now + SESSION_TTL,
                    )
                )
        except SQLAlchemyError as exc:
            log_failure("auth.open_session", exc)
            raise StoreError("stockage indisponible") from None

    async def session(self, id_hash: str, now: datetime) -> SessionInfo | None:
        try:
            async with self._engine.begin() as conn:
                row = (
                    await conn.execute(
                        sa.update(_S)
                        .where(
                            _S.c.id_hash == id_hash,
                            _S.c.expires_at > now,
                            _S.c.user_id == _U.c.id,
                            _U.c.disabled_at.is_(None),
                        )
                        .values(expires_at=now + SESSION_TTL)
                        .returning(_S.c.user_id, _U.c.name, _S.c.csrf_hash)
                    )
                ).one_or_none()
                if row is None:
                    return None
                roles = (
                    await conn.execute(sa.select(_M.c.role).where(_M.c.user_id == row.user_id))
                ).scalars()
                role = max(roles, key=rank, default=None)
        except SQLAlchemyError as exc:
            log_failure("auth.session", exc)
            raise StoreError("stockage indisponible") from None
        return None if role is None else SessionInfo(row.user_id, row.name, role, row.csrf_hash)

    async def close_session(self, id_hash: str) -> None:
        await self._run("auth.close_session", sa.delete(_S).where(_S.c.id_hash == id_hash))

    async def record_login(self, user_id: UUID | None, success: bool) -> None:
        await self._run(
            "auth.record_login",
            sa.insert(t.audit_events).values(
                actor_kind="user",
                actor_id=user_id,
                tool="auth.login",
                decision="allow" if success else "deny",
            ),
        )

    async def has_admin(self) -> bool:
        query = (
            sa.select(_M.c.user_id)
            .select_from(_M.join(_U, _U.c.id == _M.c.user_id))
            .where(_M.c.role == "org_admin", _U.c.disabled_at.is_(None))
            .limit(1)
        )
        return await self._run("auth.has_admin", query) is not None

    async def _run(self, operation: str, statement: sa.Executable) -> sa.Row[Any] | None:
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(statement)
                return result.first() if result.returns_rows else None
        except SQLAlchemyError as exc:
            log_failure(operation, exc)
            raise StoreError("stockage indisponible") from None
