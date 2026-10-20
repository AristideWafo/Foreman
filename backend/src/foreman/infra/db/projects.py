"""Projets en PostgreSQL et identités de développement."""

from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.events import ClarificationQuestion
from foreman.core.ports import CapacityExceeded
from foreman.core.projects import Project
from foreman.core.store import (
    DEV_TEAM_ID,
    DEV_TEAM_NAME,
    DEV_USER_EMAIL,
    DEV_USER_ID,
    StoreError,
    UnknownProject,
)
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure

MAX_PROJECTS = 100
# Clé du verrou transactionnel qui sérialise la création de projets (borne atomique).
PROJECT_CREATE_LOCK_KEY = 7_361_530_002


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
    except SQLAlchemyError as exc:
        log_failure("seed_dev_identity", exc)
        raise StoreError("stockage indisponible") from None


_SELECT = sa.select(
    t.projects.c.id,
    t.projects.c.name,
    t.projects.c.created_at,
    t.projects.c.team_id,
    t.teams.c.name.label("team_name"),
).select_from(t.projects.join(t.teams, t.teams.c.id == t.projects.c.team_id))


def _project(row: Any) -> Project:
    return Project(
        id=row.id,
        title=row.name,
        created_at=row.created_at,
        team_id=row.team_id,
        team_name=row.team_name,
    )


class PostgresProjectStore:
    def __init__(
        self,
        engine: AsyncEngine,
        max_projects: int = MAX_PROJECTS,
    ) -> None:
        self._engine = engine
        self._max = max_projects

    async def create(
        self, title: str, team_id: UUID = DEV_TEAM_ID, created_by: UUID = DEV_USER_ID
    ) -> Project:
        """La borne est atomique : un verrou transactionnel sérialise les créations, de sorte que
        le comptage de l'insertion voit toujours les projets déjà validés."""
        under_cap = sa.select(sa.func.count()).select_from(t.projects).scalar_subquery() < self._max
        source = sa.select(
            sa.literal(team_id, PG_UUID(as_uuid=True)),
            sa.literal(title, sa.Text),
            sa.literal(created_by, PG_UUID(as_uuid=True)),
        ).where(under_cap)
        statement = (
            sa.insert(t.projects)
            .from_select(["team_id", "name", "created_by"], source)
            .returning(t.projects.c.id)
        )
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    sa.select(sa.func.pg_advisory_xact_lock(PROJECT_CREATE_LOCK_KEY))
                )
                created = (await conn.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            log_failure("project.create", exc)
            raise StoreError("stockage indisponible") from None
        if created is None:
            raise CapacityExceeded
        project = await self.get(created)
        if project is None:  # supprimé entre l'insertion et la lecture : traité comme une panne
            raise StoreError("stockage indisponible")
        return project

    async def get(self, project_id: UUID) -> Project | None:
        try:
            async with self._engine.connect() as conn:
                row = (await conn.execute(_SELECT.where(t.projects.c.id == project_id))).first()
        except SQLAlchemyError as exc:
            log_failure("project.get", exc)
            raise StoreError("stockage indisponible") from None
        return None if row is None else _project(row)

    async def list(self, team_ids: Collection[UUID] | None = None) -> list[Project]:
        statement = _SELECT.order_by(t.projects.c.created_at.desc(), t.projects.c.id).limit(
            self._max
        )
        if team_ids is not None:
            statement = statement.where(t.projects.c.team_id.in_(list(team_ids)))
        try:
            async with self._engine.connect() as conn:
                rows = (await conn.execute(statement)).all()
        except SQLAlchemyError as exc:
            log_failure("project.list", exc)
            raise StoreError("stockage indisponible") from None
        return [_project(r) for r in rows]

    async def get_open_questions(self, project_id: UUID) -> Sequence[ClarificationQuestion]:
        statement = sa.select(t.projects.c.open_questions).where(t.projects.c.id == project_id)
        try:
            async with self._engine.connect() as conn:
                raw = (await conn.execute(statement)).scalar_one_or_none()
        except SQLAlchemyError as exc:
            log_failure("project.get_open_questions", exc)
            raise StoreError("stockage indisponible") from None
        return [ClarificationQuestion.model_validate(item) for item in raw or []]

    async def set_open_questions(
        self, project_id: UUID, questions: Sequence[ClarificationQuestion]
    ) -> None:
        statement = (
            sa.update(t.projects)
            .where(t.projects.c.id == project_id)
            .values(open_questions=[q.model_dump(mode="json") for q in questions])
            .returning(t.projects.c.id)
        )
        try:
            async with self._engine.begin() as conn:
                updated = (await conn.execute(statement)).one_or_none()
        except SQLAlchemyError as exc:
            log_failure("project.set_open_questions", exc)
            raise StoreError("stockage indisponible") from None
        if updated is None:
            raise UnknownProject
