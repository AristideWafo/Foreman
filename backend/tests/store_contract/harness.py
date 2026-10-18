"""Bancs de la suite de contrat : mémoire et PostgreSQL."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.ports import ProjectStore
from foreman.core.store import DEV_USER_ID, Lease, Stores
from foreman.infra.db import tables as t
from foreman.infra.db.projects import PostgresProjectStore
from foreman.infra.in_memory import InMemoryProjectStore, MemoryState


class Harness(Protocol):
    projects: ProjectStore
    stores: Stores

    def bounded_projects(self, max_projects: int) -> ProjectStore:
        """Un dépôt de projets avec une borne, sur la même « base » que le banc."""
        ...

    async def expire_lease(self, lease: Lease) -> None:
        """Fait expirer le bail comme le temps le ferait."""
        ...


class ManualClock:
    """Horloge du banc mémoire : avance seulement quand le test le décide."""

    def __init__(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class MemoryHarness:
    projects: ProjectStore
    stores: Stores
    clock: ManualClock
    state: MemoryState

    def bounded_projects(self, max_projects: int) -> ProjectStore:
        return InMemoryProjectStore(max_projects=max_projects)

    async def expire_lease(self, lease: Lease) -> None:
        self.clock.now += timedelta(hours=1)


@dataclass
class PostgresHarness:
    projects: ProjectStore
    stores: Stores
    engine: AsyncEngine

    def bounded_projects(self, max_projects: int) -> ProjectStore:
        return PostgresProjectStore(self.engine, max_projects=max_projects)

    async def expire_lease(self, lease: Lease) -> None:
        async with self.engine.begin() as conn:
            await conn.execute(
                sa.update(t.executions)
                .where(t.executions.c.id == lease.execution_id)
                .values(lease_expires_at=sa.func.now() - sa.text("interval '1 second'"))
            )


APPROVER = DEV_USER_ID
