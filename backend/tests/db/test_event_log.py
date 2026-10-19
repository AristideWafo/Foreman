"""Journal PostgreSQL : ordre de diffusion (verrou), rétention et fuseau (suivi de la revue S3)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from foreman.core.events import MessageData
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.infra.db.events import PostgresEventLog
from foreman.infra.db.migrate import upgrade_head
from foreman.infra.db.projects import PostgresProjectStore, seed_dev_identity


@pytest.fixture
async def engine(blank_database_url: str) -> AsyncIterator[Any]:
    await asyncio.to_thread(upgrade_head, blank_database_url)
    eng = make_engine(blank_database_url)
    await seed_dev_identity(eng)
    try:
        yield eng
    finally:
        await eng.dispose()


async def new_project(engine: Any) -> Any:
    return (await PostgresProjectStore(engine, max_projects=1_000).create("p")).id


def message(text: str) -> MessageData:
    return MessageData(role="user", text=text)


class SlowFirstCommit:
    """Retarde la fin du premier ajout (après la validation) : sans verrou, le second le double."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._first = True

    def begin(self) -> Any:
        inner, slow, self._first = self._engine.begin(), self._first, False

        class _Ctx:
            async def __aenter__(self) -> Any:
                return await inner.__aenter__()

            async def __aexit__(self, *exc: Any) -> Any:
                result = await inner.__aexit__(*exc)
                if slow:
                    await asyncio.sleep(0.3)
                return result

        return _Ctx()


async def test_delivery_order_follows_seq_even_when_the_first_append_finishes_late(
    engine: Any,
) -> None:
    project, turn = await new_project(engine), uuid4()
    log = PostgresEventLog(SlowFirstCommit(engine))  # type: ignore[arg-type]
    subscription = log.subscribe(project)
    await asyncio.gather(
        log.append(project, turn, message("1")),
        log.append(project, turn, message("2")),
    )
    delivered = [await subscription.next(), await subscription.next()]
    assert [e.seq for e in delivered if e is not None] == [1, 2]
    subscription.close()


async def test_retention_keeps_only_the_latest_events_per_project(engine: Any) -> None:
    project, other, turn = await new_project(engine), await new_project(engine), uuid4()
    log = PostgresEventLog(engine, max_events=3)
    for n in range(5):
        await log.append(project, turn, message(str(n)))
    await log.append(other, turn, message("autre"))

    assert [e.seq for e in await log.read_after(project, 0)] == [3, 4, 5]
    async with engine.connect() as conn:
        rows = (
            await conn.execute(sa.select(sa.func.count()).select_from(t.project_events))
        ).scalar_one()
    assert rows == 4  # 3 conservés + 1 de l'autre projet, intact
    assert (await log.append(project, turn, message("suite"))).seq == 6  # seq ne repart pas


async def test_event_time_does_not_depend_on_the_database_time_zone(
    blank_database_url: str,
) -> None:
    await asyncio.to_thread(upgrade_head, blank_database_url)
    url = make_url(blank_database_url).set(query={"options": "-c timezone=Pacific/Kiritimati"})
    eng = make_engine(url.render_as_string(hide_password=False))
    try:
        await seed_dev_identity(eng)
        project = await new_project(eng)
        log = PostgresEventLog(eng)
        event = await log.append(project, uuid4(), message("x"))
        (read,) = await log.read_after(project, 0)
    finally:
        await eng.dispose()
    assert read.at == event.at  # même instant (UTC+14 en session)
    assert read.at.utcoffset() is not None
