"""Stockage en mémoire borné (un seul worker ; l'état est perdu au redémarrage)."""

import asyncio
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from foreman.core.events import AnyEvent, EventData, make_event
from foreman.core.ports import CapacityExceeded, ProjectStore
from foreman.core.projects import Project
from foreman.core.store import (
    LEASE_TTL_S,
    MAX_AUDIT_DURATION_MS,
    MAX_RESUMABLE,
    ApprovalRefused,
    ApprovalResult,
    Approved,
    AuditEntry,
    CompletedReservation,
    DuplicateResource,
    ExecutionRecord,
    ExecutionRef,
    ExecutionState,
    InvalidTransition,
    Lease,
    NewPlan,
    NewReservation,
    NewResource,
    OrphanReservation,
    PlanRecord,
    Reservation,
    ResourceRecord,
    StaleLease,
    StepRecord,
    StepStatus,
    StoreError,
    Stores,
    UnknownProject,
    ensure_audit_scope,
    steps_of,
)

MAX_PROJECTS = 100
MAX_EVENTS_PER_PROJECT = 1_000
SUBSCRIBER_QUEUE_SIZE = 100
MAX_SUBSCRIBERS_PER_PROJECT = 20
MAX_SUBSCRIBERS_TOTAL = 200


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
        max_subscribers_per_project: int = MAX_SUBSCRIBERS_PER_PROJECT,
        max_subscribers_total: int = MAX_SUBSCRIBERS_TOTAL,
    ) -> None:
        self._max_events = max_events
        self._queue_size = queue_size
        self._max_subscribers_per_project = max_subscribers_per_project
        self._max_subscribers_total = max_subscribers_total
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

    def has_subscriber_capacity(self, project_id: UUID) -> bool:
        total = sum(len(subscribers) for subscribers in self._subscribers.values())
        return (
            self.subscriber_count(project_id) < self._max_subscribers_per_project
            and total < self._max_subscribers_total
        )

    def subscribe(self, project_id: UUID) -> _Subscription:
        if not self.has_subscriber_capacity(project_id):
            raise CapacityExceeded
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


# --- Moteur : plans, exécutions, registre, audit (mêmes règles que les dépôts PostgreSQL) ------

Clock = Callable[[], datetime]
_ACTIVE_STATES = ("running", "awaiting_permission", "awaiting_remediation")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Step:
    id: UUID
    seq: int
    tool: str
    params: Mapping[str, object]
    idempotency_key: str
    status: StepStatus = "pending"
    result: Mapping[str, object] | None = None


@dataclass(slots=True)
class _Execution:
    id: UUID
    plan_id: UUID
    project_id: UUID
    autonomy_level: int
    steps: list[_Step]
    state: ExecutionState = "running"
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    lease_epoch: int = 0


@dataclass(slots=True)
class _Plan:
    record: PlanRecord
    approval_id: UUID | None = None
    execution_id: UUID | None = None


@dataclass(slots=True)
class MemoryState:
    """État partagé des dépôts en mémoire (une « base » pour un processus)."""

    clock: Clock = _utc_now
    plans: dict[UUID, _Plan] = field(default_factory=dict)
    executions: dict[UUID, _Execution] = field(default_factory=dict)
    idempotency: dict[tuple[UUID, str], Mapping[str, object] | None] = field(default_factory=dict)
    resources: dict[tuple[str, str, str], ResourceRecord] = field(default_factory=dict)
    audit: list[AuditEntry] = field(default_factory=list)


def _check_audit(entry: AuditEntry) -> None:
    """Mêmes bornes que la table (`duration_ms` est un entier 32 bits)."""
    if not entry.actor_kind:
        raise StoreError("audit invalide")
    if entry.duration_ms is not None and not 0 <= entry.duration_ms <= MAX_AUDIT_DURATION_MS:
        raise StoreError("audit invalide")


class InMemoryPlanStore:
    def __init__(self, state: MemoryState, projects: ProjectStore | None = None) -> None:
        self._s = state
        self._projects = projects

    async def create(self, plan: NewPlan) -> PlanRecord:
        steps_of(plan.content)  # contenu valide
        if self._projects is not None and await self._projects.get(plan.project_id) is None:
            raise UnknownProject  # comme la clé étrangère de PostgreSQL
        previous = [
            p.record.version
            for p in self._s.plans.values()
            if p.record.project_id == plan.project_id
        ]
        record = PlanRecord(
            id=uuid4(),
            project_id=plan.project_id,
            version=1 + max(previous, default=0),
            content=plan.content,
            content_hash=plan.content_hash,
            skills_used=plan.skills_used,
            status="proposed",
            created_at=self._s.clock(),
            expires_at=plan.expires_at,
        )
        self._s.plans[record.id] = _Plan(record)
        return record

    async def get(self, project_id: UUID, plan_id: UUID) -> PlanRecord | None:
        found = self._s.plans.get(plan_id)
        return found.record if found and found.record.project_id == project_id else None

    async def approve(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        autonomy_level: int,
    ) -> ApprovalResult:
        entry = self._s.plans.get(plan_id)
        if entry is None or entry.record.project_id != project_id:
            return ApprovalRefused("not_found")
        record = entry.record
        if plan_hash != record.content_hash:
            return ApprovalRefused("plan_hash_mismatch")
        if record.status == "dev_approved" and entry.approval_id and entry.execution_id:
            return Approved(entry.approval_id, entry.execution_id, created=False)
        if record.status != "proposed" or record.expires_at <= self._s.clock():
            return ApprovalRefused("plan_not_approvable")
        if any(
            e.project_id == project_id and e.state in _ACTIVE_STATES
            for e in self._s.executions.values()
        ):
            return ApprovalRefused("execution_in_progress")
        execution_id = uuid4()
        execution = _Execution(
            id=execution_id,
            plan_id=plan_id,
            project_id=project_id,
            autonomy_level=autonomy_level,
            steps=[
                _Step(uuid4(), b.seq, b.tool, b.params, b.idempotency_key)
                for b in (s.bound_to(execution_id) for s in steps_of(record.content))
            ],
        )
        self._s.executions[execution.id] = execution
        entry.record = replace(record, status="dev_approved")
        entry.approval_id, entry.execution_id = uuid4(), execution.id
        return Approved(entry.approval_id, execution.id, created=True)


def _step_record(step: _Step) -> StepRecord:
    return StepRecord(
        step.id, step.seq, step.tool, step.params, step.idempotency_key, step.status, step.result
    )


class InMemoryExecutionStore:
    def __init__(self, state: MemoryState) -> None:
        self._s = state

    async def get(self, project_id: UUID, execution_id: UUID) -> ExecutionRecord | None:
        e = self._s.executions.get(execution_id)
        if e is None or e.project_id != project_id:
            return None
        steps = [_step_record(s) for s in sorted(e.steps, key=lambda s: s.seq)]
        return ExecutionRecord(e.id, e.plan_id, e.project_id, e.state, e.autonomy_level, steps)

    async def list_resumable(self) -> list[ExecutionRef]:
        running = [e for e in self._s.executions.values() if e.state == "running"]
        return [ExecutionRef(e.project_id, e.id) for e in running[:MAX_RESUMABLE]]

    async def claim_lease(
        self, execution_id: UUID, owner: str, ttl_s: int = LEASE_TTL_S
    ) -> Lease | None:
        e = self._s.executions.get(execution_id)
        now = self._s.clock()
        if e is None or e.state != "running":
            return None
        free = e.lease_owner is None or e.lease_expires_at is None or e.lease_expires_at < now
        if not (free or e.lease_owner == owner):
            return None
        e.lease_owner, e.lease_expires_at = owner, now + timedelta(seconds=ttl_s)
        e.lease_epoch += 1
        return Lease(e.id, owner, e.lease_epoch)

    def _held(self, lease: Lease) -> _Execution:
        e = self._s.executions.get(lease.execution_id)
        if e is None or e.lease_owner != lease.owner or e.lease_epoch != lease.epoch:
            raise StaleLease
        return e

    async def renew(self, lease: Lease, ttl_s: int = LEASE_TTL_S) -> bool:
        try:
            e = self._held(lease)
        except StaleLease:
            return False
        now = self._s.clock()
        if e.state != "running" or e.lease_expires_at is None or e.lease_expires_at < now:
            return False  # un bail expiré se reprend (`claim_lease`), il ne se renouvelle pas
        e.lease_expires_at = now + timedelta(seconds=ttl_s)
        return True

    async def next_step(self, execution_id: UUID) -> StepRecord | None:
        e = self._s.executions.get(execution_id)
        if e is None:
            return None
        pending = [s for s in sorted(e.steps, key=lambda s: s.seq) if s.status != "succeeded"]
        return _step_record(pending[0]) if pending else None

    async def reserve_idempotency(self, lease: Lease, step_seq: int) -> Reservation:
        e = self._held(lease)
        step = next((s for s in e.steps if s.seq == step_seq), None)
        if e.state != "running" or step is None or step.status not in ("pending", "running"):
            raise InvalidTransition
        key = (e.project_id, step.idempotency_key)
        step.status = "running"  # l'étape est prise en charge, quelle que soit la réponse
        if key in self._s.idempotency:
            previous = self._s.idempotency[key]
            return OrphanReservation() if previous is None else CompletedReservation(previous)
        self._s.idempotency[key] = None
        return NewReservation()

    async def complete_step(
        self,
        lease: Lease,
        step_seq: int,
        result: Mapping[str, object],
        created_resources: Sequence[NewResource],
        audit: Sequence[AuditEntry],
    ) -> None:
        e = self._held(lease)
        step = next((s for s in e.steps if s.seq == step_seq), None)
        if e.state != "running" or step is None or step.status != "running":
            raise InvalidTransition
        # Tout est validé avant la première écriture : tout ou rien.
        ensure_audit_scope(audit, e.project_id, e.id)
        for entry in audit:
            _check_audit(entry)
        keys = [(r.provider, r.resource_type, r.external_id) for r in created_resources]
        if len(set(keys)) != len(keys) or any(k in self._s.resources for k in keys):
            raise DuplicateResource
        for r in created_resources:
            self._s.resources[(r.provider, r.resource_type, r.external_id)] = ResourceRecord(
                id=uuid4(),
                project_id=e.project_id,
                execution_id=e.id,
                provider=r.provider,
                resource_type=r.resource_type,
                external_id=r.external_id,
                external_url=r.external_url,
                origin="created",
            )
        self._s.audit.extend(audit)
        self._s.idempotency[(e.project_id, step.idempotency_key)] = dict(result)
        step.status, step.result = "succeeded", dict(result)

    async def finish(self, lease: Lease, state: Literal["succeeded", "blocked"]) -> None:
        e = self._held(lease)
        if e.state != "running":
            raise InvalidTransition
        if state == "succeeded" and any(s.status != "succeeded" for s in e.steps):
            raise InvalidTransition  # un succès exige toutes les étapes réussies
        e.state = state
        if state == "succeeded":
            plan = self._s.plans[e.plan_id]
            plan.record = replace(plan.record, status="executed")


class InMemoryResourceRegistry:
    def __init__(self, state: MemoryState) -> None:
        self._s = state

    async def contains(
        self, project_id: UUID, provider: str, resource_type: str, external_id: str
    ) -> bool:
        found = self._s.resources.get((provider, resource_type, external_id))
        return found is not None and found.project_id == project_id

    async def exists_elsewhere(
        self, project_id: UUID, provider: str, resource_type: str, external_id: str
    ) -> bool:
        found = self._s.resources.get((provider, resource_type, external_id))
        return found is not None and found.project_id != project_id

    async def list_for_project(self, project_id: UUID) -> list[ResourceRecord]:
        return [r for r in self._s.resources.values() if r.project_id == project_id]


class InMemoryAuditLog:
    def __init__(self, state: MemoryState) -> None:
        self._s = state

    async def append(self, entry: AuditEntry) -> None:
        _check_audit(entry)
        self._s.audit.append(entry)

    async def list_for_project(self, project_id: UUID, limit: int = 200) -> list[AuditEntry]:
        return [e for e in self._s.audit if e.project_id == project_id][:limit]


def in_memory_stores(
    clock: Clock = _utc_now, projects: ProjectStore | None = None
) -> tuple[MemoryState, Stores]:
    """Avec `projects`, un plan d'un projet inconnu est refusé comme en PostgreSQL."""
    state = MemoryState(clock=clock)
    return state, Stores(
        plans=InMemoryPlanStore(state, projects),
        executions=InMemoryExecutionStore(state),
        registry=InMemoryResourceRegistry(state),
        audit=InMemoryAuditLog(state),
    )
