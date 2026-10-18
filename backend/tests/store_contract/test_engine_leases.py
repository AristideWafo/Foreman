"""Deux moteurs, une exécution : chaque étape une fois, reprise après expiration du bail.

Tourne sur la mémoire et sur PostgreSQL (banc partagé) avec une gateway factice qui compte les
appels : on vérifie le moteur et les garanties du dépôt, pas les adaptateurs.
"""

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from harness import Harness

from foreman.core.approval import ApprovalService
from foreman.core.execution.engine import ExecutionEngine
from foreman.core.gateway.port import GatewayCall, GatewayResult
from foreman.core.planning import Draft, DraftStep, Planner
from foreman.core.store import Approved, AuditEntry, Lease, Reservation, Stores
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog


def far_future() -> datetime:
    """Le plan expire bien après l'horloge du banc mémoire (2030) comme celle de la base."""
    return datetime(2100, 1, 1, tzinfo=UTC)


REF = {"$from": {"step": 1, "field": "group_id"}}


class CountingGateway:
    """Gateway factice : une sortie par étape, et le compte des appels par numéro d'étape."""

    def __init__(self) -> None:
        self.calls: Counter[int] = Counter()
        self.parents: dict[int, object] = {}

    async def call(self, call: GatewayCall) -> GatewayResult:
        await asyncio.sleep(0)  # laisse l'autre moteur s'intercaler
        self.calls[call.step_seq] += 1
        self.parents[call.step_seq] = call.params.get("parent_group_id")
        return GatewayResult(
            output={"group_id": 1000 + call.step_seq},
            logs=[],
            resources=(),
            audit=AuditEntry(
                actor_kind="engine",
                project_id=call.project_id,
                execution_id=call.execution_id,
                step_seq=call.step_seq,
                decision="allow",
            ),
        )


class WorkerKilled(BaseException):
    """Simule la mort du processus (n'est pas une `Exception` : le moteur ne la rattrape pas)."""


class DyingExecutionStore:
    """Délègue au dépôt réel, mais le processus « meurt » avant de réserver l'étape `die_at`."""

    def __init__(self, inner: Stores, die_at: int) -> None:
        self._inner = inner.executions
        self._die_at = die_at

    async def reserve_idempotency(self, lease: Lease, step_seq: int) -> Reservation:
        if step_seq == self._die_at:
            raise WorkerKilled
        return await self._inner.reserve_idempotency(lease, step_seq)

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@dataclass
class Bench:
    project: UUID
    execution: UUID
    gateway: CountingGateway
    engine: ExecutionEngine
    stores: Stores


async def approved_execution(h: Harness, stores: Stores | None = None) -> Bench:
    catalog = load_catalog(environment="staging")
    project = (await h.projects.create("p")).id
    draft = Draft(
        title="Groupes",
        summary="Deux groupes puis un contrôle",
        steps=[
            DraftStep(
                "Racine",
                "gitlab.create_group",
                {"parent_group_id": 1000, "name": "A", "path": "aa"},
            ),
            DraftStep(
                "Sous-groupe",
                "gitlab.create_group",
                {"parent_group_id": REF, "name": "B", "path": "bb"},
            ),
            DraftStep("Santé", "server.healthcheck", {"environment": "staging", "project": "aa"}),
        ],
    )
    record, _ = await Planner(catalog, h.stores.plans, clock=far_future).propose(project, draft)
    events = InMemoryEventLog()
    approved = await ApprovalService(catalog, h.stores, events).approve(
        project, record.id, record.content_hash
    )
    assert isinstance(approved, Approved)
    gateway = CountingGateway()
    engine = ExecutionEngine(
        catalog=catalog, stores=stores or h.stores, gateway=gateway, events=events
    )
    return Bench(project, approved.execution_id, gateway, engine, h.stores)


async def test_two_engines_run_each_step_once_and_a_dead_one_is_replaced(harness: Harness) -> None:
    # Deux moteurs en même temps : un seul tient le bail, chaque étape part une fois.
    first = await approved_execution(harness)
    second = ExecutionEngine(
        catalog=load_catalog(environment="staging"),
        stores=harness.stores,
        gateway=first.gateway,
        events=InMemoryEventLog(),
    )
    await asyncio.gather(
        first.engine.run(first.project, first.execution),
        second.run(first.project, first.execution),
    )
    execution = await harness.stores.executions.get(first.project, first.execution)
    assert execution is not None and execution.state == "succeeded"
    assert first.gateway.calls == Counter({1: 1, 2: 1, 3: 1})
    assert first.gateway.parents[2] == 1001  # la référence $from est résolue par le moteur
    assert all("{execution_id}" not in s.idempotency_key for s in execution.steps)
    assert str(first.execution) in execution.steps[2].idempotency_key

    # Le processus meurt entre l'étape 1 et l'étape 2 ; le bail encore valide protège l'exécution.
    dying_stores = Stores(
        plans=harness.stores.plans,
        executions=DyingExecutionStore(harness.stores, die_at=2),  # type: ignore[arg-type]
        registry=harness.stores.registry,
        audit=harness.stores.audit,
    )
    bench = await approved_execution(harness, dying_stores)
    with pytest.raises(WorkerKilled):
        await bench.engine.run(bench.project, bench.execution)
    assert bench.gateway.calls == Counter({1: 1})
    healthy = ExecutionEngine(
        catalog=load_catalog(environment="staging"),
        stores=harness.stores,
        gateway=bench.gateway,
        events=InMemoryEventLog(),
    )
    await healthy.run(bench.project, bench.execution)
    assert bench.gateway.calls == Counter({1: 1})  # bail non expiré : rien ne repart
    await harness.expire_lease(Lease(bench.execution, "ancien", 0))
    await healthy.run(bench.project, bench.execution)
    resumed = await harness.stores.executions.get(bench.project, bench.execution)
    assert resumed is not None and resumed.state == "succeeded"
    assert bench.gateway.calls == Counter({1: 1, 2: 1, 3: 1})  # l'étape 1 n'est pas rejouée
    assert await harness.stores.executions.list_resumable() == []
