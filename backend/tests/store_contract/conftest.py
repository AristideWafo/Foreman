"""Fixture paramétrée : la même suite de contrat tourne sur la mémoire et sur PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from harness import Harness, ManualClock, MemoryHarness, PostgresHarness

from foreman.infra.db.engine import make_engine
from foreman.infra.db.events import PostgresEventLog
from foreman.infra.db.migrate import upgrade_head
from foreman.infra.db.projects import PostgresProjectStore, seed_dev_identity
from foreman.infra.db.stores import postgres_stores
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores


@pytest.fixture(params=["memory", "postgres"])
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    if request.param == "memory":
        clock = ManualClock()
        projects = InMemoryProjectStore(max_projects=1_000)
        state, stores = in_memory_stores(clock, projects)
        yield MemoryHarness(projects, stores, clock, state, InMemoryEventLog())
        return
    url: str = request.getfixturevalue("blank_database_url")
    await asyncio.to_thread(upgrade_head, url)
    engine = make_engine(url)
    try:
        await seed_dev_identity(engine)
        yield PostgresHarness(
            PostgresProjectStore(engine, max_projects=1_000),
            postgres_stores(engine),
            engine,
            PostgresEventLog(engine),
        )
    finally:
        await engine.dispose()
