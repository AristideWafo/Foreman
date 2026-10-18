"""Abonnés au direct d'un projet, communs au journal en mémoire et au journal PostgreSQL.

Tout se passe dans la boucle asynchrone, sans appel bloquant : une file bornée par abonné, un
plafond par projet et un plafond global.
"""

import asyncio
from uuid import UUID

from foreman.core.events import AnyEvent
from foreman.core.ports import CapacityExceeded

SUBSCRIBER_QUEUE_SIZE = 100
MAX_SUBSCRIBERS_PER_PROJECT = 20
MAX_SUBSCRIBERS_TOTAL = 200


class Subscription:
    def __init__(self, hub: "SubscriberHub", project_id: UUID, queue_size: int) -> None:
        self._hub = hub
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
        self._hub.unsubscribe(self._project_id, self)
        while not self._queue.empty():
            self._queue.get_nowait()
        self._queue.put_nowait(None)


class SubscriberHub:
    def __init__(
        self,
        queue_size: int = SUBSCRIBER_QUEUE_SIZE,
        max_subscribers_per_project: int = MAX_SUBSCRIBERS_PER_PROJECT,
        max_subscribers_total: int = MAX_SUBSCRIBERS_TOTAL,
    ) -> None:
        self._queue_size = queue_size
        self._max_subscribers_per_project = max_subscribers_per_project
        self._max_subscribers_total = max_subscribers_total
        self._subscribers: dict[UUID, list[Subscription]] = {}
        self._waiters: list[tuple[UUID, int, asyncio.Future[None]]] = []

    def _publish(self, project_id: UUID, event: AnyEvent) -> None:
        """Synchrone : aucune attente entre deux abonnés, donc aucun entrelacement possible."""
        for subscriber in list(self._subscribers.get(project_id, ())):
            subscriber.offer(event)

    def has_subscriber_capacity(self, project_id: UUID) -> bool:
        total = sum(len(subscribers) for subscribers in self._subscribers.values())
        return (
            self.subscriber_count(project_id) < self._max_subscribers_per_project
            and total < self._max_subscribers_total
        )

    def subscribe(self, project_id: UUID) -> Subscription:
        if not self.has_subscriber_capacity(project_id):
            raise CapacityExceeded
        subscription = Subscription(self, project_id, self._queue_size)
        self._subscribers.setdefault(project_id, []).append(subscription)
        self._notify_waiters(project_id)
        return subscription

    def unsubscribe(self, project_id: UUID, subscription: Subscription) -> None:
        subscribers = self._subscribers.get(project_id, [])
        if subscription in subscribers:
            subscribers.remove(subscription)
        if not subscribers:
            self._subscribers.pop(project_id, None)
        self._notify_waiters(project_id)

    def subscriber_count(self, project_id: UUID) -> int:
        return len(self._subscribers.get(project_id, ()))

    async def wait_for_subscriber_count(self, project_id: UUID, count: int) -> None:
        """Tests uniquement : attend, sans interrogation, que les abonnés soient `count`."""
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
