"""Membres de l'équipe de développement en PostgreSQL (`users` et `memberships`)."""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.identity import Member, Role
from foreman.core.store import DEV_TEAM_ID, StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure


class PostgresMemberStore:
    def __init__(self, engine: AsyncEngine, team_id: UUID = DEV_TEAM_ID) -> None:
        self._engine = engine
        self._team_id = team_id

    async def role_of(self, user_id: UUID) -> Role | None:
        statement = sa.select(t.memberships.c.role).where(
            t.memberships.c.user_id == user_id, t.memberships.c.team_id == self._team_id
        )
        try:
            async with self._engine.connect() as conn:
                return (await conn.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            log_failure("members.role_of", exc)
            raise StoreError("stockage indisponible") from None

    async def sync(self, members: Sequence[Member]) -> None:
        """Remplace les rôles de l'équipe en une transaction. Les `users` ne sont jamais supprimés
        (les plans et approbations les référencent) ; seul le rôle disparaît."""
        try:
            async with self._engine.begin() as conn:
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
