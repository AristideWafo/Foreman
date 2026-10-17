"""Stockage en mémoire borné (un seul worker ; l'état est perdu au redémarrage)."""

import asyncio
from collections import deque
from datetime import UTC, datetime
from uuid import UUID, uuid4

from foreman.core.events import AnyEvent, EventData, make_event
from foreman.core.ports import CapacityExceeded
from foreman.core.projects import Project

MAX_PROJECTS = 100
MAX_EVENTS_PER_PROJECT = 1_000
SUBSCRIBER_QUEUE_SIZE = 100


class InMemoryProjectStore:
    def __init__(self, max_projects: int = MAX_PROJECTS) -> None:
        self._max = max_projects
        self._projects: dict[UUID, Project] = {}

    async def create(self, title: str) -> Project:
        if len(self._projects) >= self._max:
            raise CapacityExceeded
        project = Project(id=uuid4(), title=title, created_at=datetime.now(UTC))
        self._projects[project.id] = project
        return project

    async def get(self, project_id: UUID) -> Project | None:
        return self._projects.get(project_id)


class _Subscription:
    def __init__(self, log: "InMemoryEventLog", project_id: UUID, queue_size: int) -> None:
        self._log = log
        self._project_id = project_id
        self._queue: asyncio.Queue[AnyEvent | None] = asyncio.Queue(maxsize=queue_size)
        self._closed = False

    def offer(self, event: AnyEvent) -> bool:
        """Faux si l'abonné est trop lent : il est alors coupé (il reprendra via `seq`)."""
        if self._closed:
            return True
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._terminate()
            return False
        return True

    async def next(self) -> AnyEvent | None:
        event = await self._queue.get()
        if event is None:
            self._queue.put_nowait(None)  # la fermeture reste observable
        return event

    def close(self) -> None:
        self._terminate()

    def _terminate(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._log.unsubscribe(self._project_id, self)
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)


class InMemoryEventLog:
    def __init__(
        self,
        max_events: int = MAX_EVENTS_PER_PROJECT,
        queue_size: int = SUBSCRIBER_QUEUE_SIZE,
    ) -> None:
        self._max_events = max_events
        self._queue_size = queue_size
        self._events: dict[UUID, deque[AnyEvent]] = {}
        self._last_seq: dict[UUID, int] = {}
        self._subscribers: dict[UUID, list[_Subscription]] = {}
        self._waiters: list[tuple[UUID, int, asyncio.Future[None]]] = []

    async def append(self, project_id: UUID, turn_id: UUID, data: EventData) -> AnyEvent:
        seq = self._last_seq.get(project_id, 0) + 1
        event = make_event(seq, project_id, turn_id, data)
        self._last_seq[project_id] = seq
        self._events.setdefault(project_id, deque(maxlen=self._max_events)).append(event)
        for subscriber in list(self._subscribers.get(project_id, ())):
            subscriber.offer(event)
        return event

    async def read_after(self, project_id: UUID, seq: int) -> list[AnyEvent]:
        return [e for e in self._events.get(project_id, ()) if e.seq > seq]

    def subscribe(self, project_id: UUID) -> _Subscription:
        subscription = _Subscription(self, project_id, self._queue_size)
        self._subscribers.setdefault(project_id, []).append(subscription)
        self._notify_waiters(project_id)
        return subscription

    def unsubscribe(self, project_id: UUID, subscription: _Subscription) -> None:
        subscribers = self._subscribers.get(project_id, [])
        if subscription in subscribers:
            subscribers.remove(subscription)
        if not subscribers:
            self._subscribers.pop(project_id, None)
        self._notify_waiters(project_id)

    def subscriber_count(self, project_id: UUID) -> int:
        return len(self._subscribers.get(project_id, ()))

    async def wait_for_subscriber_count(self, project_id: UUID, count: int) -> None:
        """Attend (sans interrogation) que le nombre d'abonnés atteigne `count`."""
        if self.subscriber_count(project_id) == count:
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (project_id, count, waiter)
        self._waiters.append(entry)
        try:
            await waiter
        finally:
            self._waiters.remove(entry)

    def _notify_waiters(self, project_id: UUID) -> None:
        current = self.subscriber_count(project_id)
        for waited_project, count, waiter in self._waiters:
            if waited_project == project_id and count == current and not waiter.done():
                waiter.set_result(None)
