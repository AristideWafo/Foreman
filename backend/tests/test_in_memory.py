from uuid import uuid4

import pytest

from foreman.core.events import MessageData
from foreman.core.ports import CapacityExceeded
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore


async def test_project_store_refuses_beyond_its_bound() -> None:
    store = InMemoryProjectStore(max_projects=2)
    await store.create("a")
    await store.create("b")
    with pytest.raises(CapacityExceeded):
        await store.create("c")


async def test_seq_is_contiguous_per_project_and_survives_eviction() -> None:
    log = InMemoryEventLog(max_events=3)
    a, b, turn = uuid4(), uuid4(), uuid4()
    for i in range(5):
        event = await log.append(a, turn, MessageData(role="user", text=str(i)))
        assert event.seq == i + 1
    assert (await log.append(b, turn, MessageData(role="user", text="x"))).seq == 1
    assert [e.seq for e in await log.read_after(a, 0)] == [3, 4, 5]
    assert [e.seq for e in await log.read_after(a, 4)] == [5]


async def test_slow_subscriber_is_cut_and_the_others_keep_receiving() -> None:
    log = InMemoryEventLog(queue_size=2)
    project, turn = uuid4(), uuid4()
    slow, fast = log.subscribe(project), log.subscribe(project)
    received = []
    for i in range(3):
        await log.append(project, turn, MessageData(role="user", text=str(i)))
        received.append(await fast.next())
    assert await slow.next() is None  # coupé au débordement
    assert log.subscriber_count(project) == 1
    assert [e.seq for e in received if e] == [1, 2, 3]
    fast.close()
    assert log.subscriber_count(project) == 0
