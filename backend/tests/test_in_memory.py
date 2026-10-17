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


async def test_subscriber_caps_per_project_and_in_total_and_a_close_frees_a_slot() -> None:
    log = InMemoryEventLog(max_subscribers_per_project=2, max_subscribers_total=3)
    a, b = uuid4(), uuid4()
    first, second = log.subscribe(a), log.subscribe(a)
    assert not log.has_subscriber_capacity(a)  # plafond par projet
    with pytest.raises(CapacityExceeded):
        log.subscribe(a)
    third = log.subscribe(b)
    assert not log.has_subscriber_capacity(b)  # plafond global (3 abonnés)
    first.close()
    assert log.has_subscriber_capacity(a)
    for subscription in (second, third):
        subscription.close()
    assert log.subscriber_count(a) == log.subscriber_count(b) == 0
