"""Registre des ressources gérées. Les écritures passent uniquement par `complete_step`."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.store import ResourceRecord, StoreError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import log_failure


class PostgresResourceRegistry:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def contains(self, provider: str, resource_type: str, external_id: str) -> bool:
        statement = sa.select(
            sa.exists().where(
                t.managed_resources.c.provider == provider,
                t.managed_resources.c.resource_type == resource_type,
                t.managed_resources.c.external_id == external_id,
                t.managed_resources.c.deleted_at.is_(None),
            )
        )
        try:
            async with self._engine.connect() as conn:
                return bool((await conn.execute(statement)).scalar_one())
        except DBAPIError as exc:
            log_failure("registry.contains", exc)
            raise StoreError("stockage indisponible") from None

    async def list_for_project(self, project_id: UUID) -> list[ResourceRecord]:
        statement = (
            sa.select(*t.managed_resources.c)
            .where(
                t.managed_resources.c.project_id == project_id,
                t.managed_resources.c.deleted_at.is_(None),
            )
            .order_by(t.managed_resources.c.created_at, t.managed_resources.c.id)
        )
        try:
            async with self._engine.connect() as conn:
                rows = (await conn.execute(statement)).all()
        except DBAPIError as exc:
            log_failure("registry.list", exc)
            raise StoreError("stockage indisponible") from None
        return [
            ResourceRecord(
                id=r.id,
                project_id=r.project_id,
                execution_id=r.execution_id,
                provider=r.provider,
                resource_type=r.resource_type,
                external_id=r.external_id,
                external_url=r.external_url,
                origin=r.origin,
            )
            for r in rows
        ]
