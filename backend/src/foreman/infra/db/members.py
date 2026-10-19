"""Membres de l'équipe de développement en PostgreSQL (`users` et `memberships`)."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.accounts import InvalidInviterChain, rank, validate_inviter_chain
from foreman.core.identity import Member, Role
from foreman.core.store import DEV_TEAM_ID, StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

_M, _U = t.memberships, t.users

# Remonte `invited_by` (borné à 11 maillons, anti-cycle) ; « admin » = org_admin ou team_admin d'une
# équipe non personnelle (chacun est admin de sa propre équipe personnelle).
_CHAIN = sa.text(
    """
    WITH RECURSIVE c(id, invited_by, depth) AS (
        SELECT id, invited_by, 1 FROM users WHERE id = :start
      UNION ALL
        SELECT u.id, u.invited_by, c.depth + 1 FROM users u JOIN c ON u.id = c.invited_by
        WHERE c.depth < 11
    )
    SELECT c.id, c.invited_by, u.disabled_at IS NULL AS active,
        EXISTS (
            SELECT 1 FROM memberships m JOIN teams tm ON tm.id = m.team_id
            WHERE m.user_id = c.id
              AND (m.role = 'org_admin' OR (m.role = 'team_admin' AND NOT tm.personal))
        ) AS admin
    FROM c JOIN users u ON u.id = c.id ORDER BY c.depth
    """
)


class PostgresMemberStore:
    def __init__(self, engine: AsyncEngine, team_id: UUID = DEV_TEAM_ID) -> None:
        self._engine = engine
        self._team_id = team_id

    async def role_in(self, user_id: UUID, team_id: UUID) -> Role | None:
        statement = (
            sa.select(_M.c.role)
            .select_from(_M.join(_U, _U.c.id == _M.c.user_id))
            .where(
                _M.c.user_id == user_id,
                _U.c.disabled_at.is_(None),
                sa.or_(_M.c.role == "org_admin", _M.c.team_id == team_id),
            )
        )
        roles = await self._all("members.role_in", statement)
        return max((r for (r,) in roles), key=rank, default=None)

    async def teams_of(self, user_id: UUID) -> frozenset[UUID] | None:
        statement = (
            sa.select(_M.c.team_id, _M.c.role)
            .select_from(_M.join(_U, _U.c.id == _M.c.user_id))
            .where(_M.c.user_id == user_id, _U.c.disabled_at.is_(None))
        )
        rows = await self._all("members.teams_of", statement)
        if any(r.role == "org_admin" for r in rows):
            return None
        return frozenset(r.team_id for r in rows)

    async def personal_team_of(self, user_id: UUID) -> UUID | None:
        statement = (
            sa.select(_M.c.team_id)
            .select_from(_M.join(t.teams, t.teams.c.id == _M.c.team_id))
            .where(_M.c.user_id == user_id, t.teams.c.personal.is_(True))
            .order_by(_M.c.team_id)
            .limit(1)
        )
        rows = await self._all("members.personal_team_of", statement)
        return rows[0][0] if rows else None

    async def designated_admins(self, team_id: UUID) -> frozenset[UUID] | None:
        personal = await self._all(
            "members.designated_admins",
            sa.select(t.teams.c.personal).where(t.teams.c.id == team_id),
        )
        if not personal or not personal[0][0]:
            return None
        owners = await self._all(
            "members.designated_admins",
            sa.select(_M.c.user_id)
            .where(_M.c.team_id == team_id, _M.c.role == "team_admin")
            .order_by(_M.c.user_id)
            .limit(1),
        )
        if not owners:
            return frozenset()
        owner = owners[0][0]
        chain = await self._all("members.designated_admins", _CHAIN, {"start": owner})
        try:
            validate_inviter_chain(owner, {r.id: r.invited_by for r in chain})
        except InvalidInviterChain:
            return frozenset()  # chaîne cyclique ou trop profonde : repli org_admin
        for row in chain[1:]:  # du plus proche (l'inviteur direct) au plus lointain
            if row.active and row.admin:
                return frozenset({row.id})
        return frozenset()

    async def _all(
        self, operation: str, statement: sa.Executable, params: dict[str, Any] | None = None
    ) -> Sequence[sa.Row[Any]]:
        try:
            async with self._engine.connect() as conn:
                return (await conn.execute(statement, params)).all()
        except SQLAlchemyError as exc:
            log_failure(operation, exc)
            raise StoreError("stockage indisponible") from None

    async def name_of(self, user_id: UUID) -> str | None:
        statement = sa.select(t.users.c.name).where(t.users.c.id == user_id)
        try:
            async with self._engine.connect() as conn:
                return (await conn.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            log_failure("members.name_of", exc)
            raise StoreError("stockage indisponible") from None

    async def sync(self, members: Sequence[Member]) -> None:
        """Remplace les rôles de l'équipe en une transaction. Les `users` ne sont jamais supprimés
        (les plans et approbations les référencent) ; seul le rôle disparaît.

        No-op dès qu'un compte a un mot de passe : l'amorçage n'efface pas ce que l'UI a géré.
        """
        try:
            async with self._engine.begin() as conn:
                managed = sa.select(t.users.c.id).where(t.users.c.password_hash.is_not(None))
                if (await conn.execute(managed.limit(1))).first() is not None:
                    return
                await conn.execute(
                    sa.delete(t.memberships).where(t.memberships.c.team_id == self._team_id)
                )
                if not members:
                    return
                users = pg_insert(t.users).values(
                    [
                        {
                            "id": m.user_id,
                            "email": f"{m.name}@members.foreman.local",
                            "name": m.name,
                        }
                        for m in members
                    ]
                )
                await conn.execute(
                    users.on_conflict_do_update(
                        index_elements=[t.users.c.id], set_={"name": users.excluded.name}
                    )
                )
                await conn.execute(
                    sa.insert(t.memberships),
                    [
                        {"user_id": m.user_id, "team_id": self._team_id, "role": m.role}
                        for m in members
                    ],
                )
        except SQLAlchemyError as exc:
            log_failure("members.sync", exc)
            raise StoreError("stockage indisponible") from None
