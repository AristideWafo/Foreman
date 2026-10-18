"""Projets en PostgreSQL et identités de développement."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.ports import CapacityExceeded
from foreman.core.projects import Project
from foreman.core.store import (
    DEV_TEAM_ID,
    DEV_TEAM_NAME,
    DEV_USER_EMAIL,
    DEV_USER_ID,
    StoreError,
)
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

MAX_PROJECTS = 100


async def seed_dev_identity(engine: AsyncEngine) -> None:
    """Utilisateur et équipe de développement (upsert idempotent, sûr en démarrage concurrent)."""
    try:
        async with engine.begin() as conn:
            await conn.execute(
                pg_insert(t.users)
                .values(id=DEV_USER_ID, email=DEV_USER_EMAIL, name="Développeur")
                .on_conflict_do_nothing()
            )
            await conn.execute(
                pg_insert(t.teams)
                .values(id=DEV_TEAM_ID, name=DEV_TEAM_NAME)
                .on_conflict_do_nothing()
            )
    except DBAPIError as exc:
        log_failure("seed_dev_identity", exc)
        raise StoreError("stockage indisponible") from None


class PostgresProjectStore:
    def __init__(
        self,
        engine: AsyncEngine,
        team_id: UUID = DEV_TEAM_ID,
        created_by: UUID = DEV_USER_ID,
        max_projects: int = MAX_PROJECTS,
    ) -> None:
        self._engine = engine
        self._team_id = team_id
        self._created_by = created_by
        self._max = max_projects

    async def create(self, title: str) -> Project:
        """La borne est vérifiée dans la requête d'insertion ; un dépassement léger est possible
        sous forte concurrence (la borne protège la mémoire du PoC, pas un quota facturé)."""
        under_cap = sa.select(sa.func.count()).select_from(t.projects).scalar_subquery() < self._max
        source = sa.select(
            sa.literal(self._team_id, PG_UUID(as_uuid=True)),
            sa.literal(title, sa.Text),
            sa.literal(self._created_by, PG_UUID(as_uuid=True)),
        ).where(under_cap)
        statement = (
            sa.insert(t.projects)
            .from_select(["team_id", "name", "created_by"], source)
            .returning(t.projects.c.id, t.projects.c.name, t.projects.c.created_at)
        )
        try:
            async with self._engine.begin() as conn:
                row = (await conn.execute(statement)).one_or_none()
        except DBAPIError as exc:
            log_failure("project.create", exc)
            raise StoreError("stockage indisponible") from None
        if row is None:
            raise CapacityExceeded
        return Project(id=row.id, title=row.name, created_at=row.created_at)

    async def get(self, project_id: UUID) -> Project | None:
        statement = sa.select(t.projects.c.id, t.projects.c.name, t.projects.c.created_at).where(
            t.projects.c.id == project_id
        )
        try:
            async with self._engine.connect() as conn:
                row = (await conn.execute(statement)).one_or_none()
        except DBAPIError as exc:
            log_failure("project.get", exc)
            raise StoreError("stockage indisponible") from None
        return (
            None if row is None else Project(id=row.id, title=row.name, created_at=row.created_at)
        )
