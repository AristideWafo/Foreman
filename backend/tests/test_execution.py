"""Moteur d'exécution en mémoire : route d'approbation et issue d'un défaut d'adaptateur."""

import asyncio
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from pydantic import JsonValue

from foreman.bootstrap.configure import Profile, configure
from foreman.core.approval import ApprovalService
from foreman.core.execution.engine import ExecutionEngine
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.gateway.port import GatewayCall, GatewayResult
from foreman.core.identity import Principal
from foreman.core.planning import Draft, DraftStep, Planner, plan_card_id
from foreman.core.ports import AdapterResult, ToolAdapter
from foreman.core.store import DEV_USER_ID, ApprovalRefused, Approved, AuditEntry, AwaitingAdmin
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer
from foreman.surfaces.web.app import create_app
from support import DEV_PRINCIPAL, dev_members

ADAPTER_SECRET = "secret-adapter token=glpat-XXXXXXXXXXXXXXXXXXXX"  # noqa: S105 - valeur factice


async def wait_for(log: InMemoryEventLog, project_id: UUID, kind: str, **expected: str) -> None:
    """Attend (5 s au plus) un événement `card`/`turn_status` dont la charge porte `expected`."""
    subscription = log.subscribe(project_id)
    try:
        async with asyncio.timeout(5):
            while (event := await subscription.next()) is not None:
                data = event.data.model_dump(mode="json")
                if event.type == kind and all(data.get(k) == v for k, v in expected.items()):
                    return
    finally:
        subscription.close()
    raise AssertionError("flux fermé avant l'événement attendu")


async def test_approval_route_creates_one_execution_and_stays_opaque() -> None:
    state = configure(Profile.WEB)
    app = create_app(state)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project = (await client.post("/api/projects", json={})).json()["id"]
        other = (await client.post("/api/projects", json={})).json()["id"]
        pid = UUID(project)
        completed = asyncio.create_task(
            wait_for(state.events, pid, "turn_status", status="completed")
        )
        await asyncio.sleep(0)
        await client.post(f"/api/projects/{project}/messages", json={"text": "Crée Safe Eat"})
        await completed
        plans = [e for e in await state.events.read_after(pid, 0) if e.type == "card"]
        card = plans[0].data
        base = f"/api/projects/{project}/plans/{card.plan_id}/approvals"
        good = {"plan_hash": card.plan_hash, "decision": "approved"}

        bad_hash = await client.post(base, json={**good, "plan_hash": "sha256:" + "0" * 64})
        assert (bad_hash.status_code, bad_hash.json()) == (409, {"error": "plan_hash_mismatch"})
        foreign = await client.post(
            f"/api/projects/{other}/plans/{card.plan_id}/approvals", json=good
        )
        assert (foreign.status_code, foreign.json()) == (404, {"error": "not_found"})
        invalid = await client.post(base, json={**good, "decision": "rejected"})
        assert (invalid.status_code, invalid.json()) == (422, {"error": "invalid_request"})

        finished = asyncio.create_task(wait_for(state.events, pid, "card", state="succeeded"))
        await asyncio.sleep(0)
        first, second = await asyncio.gather(
            client.post(base, json=good), client.post(base, json=good)
        )
        assert sorted([first.status_code, second.status_code]) == [200, 201]
        assert first.json() == second.json()  # mêmes approval_id et execution_id
        await finished

        execution_id = first.json()["execution_id"]
        view = await client.get(f"/api/projects/{project}/executions/{execution_id}")
        assert view.status_code == 200
        assert view.json()["state"] == "succeeded"
        assert [s["status"] for s in view.json()["steps"]] == ["succeeded"] * 8
        hidden = await client.get(f"/api/projects/{other}/executions/{execution_id}")
        assert (hidden.status_code, hidden.json()) == (404, {"error": "not_found"})

        events = await state.events.read_after(pid, 0)
        approved_cards = [
            e
            for e in events
            if e.type == "card" and e.data.kind == "plan" and e.data.status == "dev_approved"
        ]
        assert len(approved_cards) == 1  # une seule approbation effective, un seul moteur
        assert approved_cards[0].data.approvable is False


class FailingOnSecondCall:
    """Adaptateur dont le second appel lève une exception chargée de secrets."""

    def __init__(self, inner: ToolAdapter) -> None:
        self.inner = inner
        self.calls = 0

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError(ADAPTER_SECRET)
        return await self.inner.execute(tool, params, idempotency_key)


async def test_an_adapter_defect_blocks_the_execution_without_leaking_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = load_catalog(environment="staging")
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    events = InMemoryEventLog()
    gitlab = FailingOnSecondCall(
        SimulatedGitLab.from_referentiel(catalog.referentiels["gitlab-groups"].data)
    )
    gateway = ToolGateway(
        catalog=catalog,
        stores=stores,
        members=dev_members(),
        adapters={
            "gitlab": gitlab,
            "server": SimulatedServer(),
            "dns": SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data),
        },
    )
    project = (await projects.create("p")).id
    ref = {"$from": {"step": 1, "field": "group_id"}}
    draft = Draft(
        title="Groupes",
        summary="Trois groupes",
        environment="staging",
        steps=[
            DraftStep(
                "Racine",
                "gitlab.create_group",
                {"parent_group_id": 1000, "name": "A", "path": "aa"},
            ),
            DraftStep(
                "Backend",
                "gitlab.create_group",
                {"parent_group_id": ref, "name": "B", "path": "bb"},
            ),
            DraftStep(
                "Frontend",
                "gitlab.create_group",
                {"parent_group_id": ref, "name": "C", "path": "cc"},
            ),
        ],
    )
    record, _ = await Planner(catalog, stores.plans, stores.registry).propose(
        project, draft, DEV_USER_ID
    )
    approved = await ApprovalService(catalog, stores, events, dev_members()).approve(
        project, record.id, record.content_hash, DEV_PRINCIPAL
    )
    assert isinstance(approved, Approved)

    caplog.set_level(logging.DEBUG)
    engine = ExecutionEngine(catalog=catalog, stores=stores, gateway=gateway, events=events)
    await engine.run(project, approved.execution_id)

    execution = await stores.executions.get(project, approved.execution_id)
    assert execution is not None and execution.state == "blocked"
    assert [s.status for s in execution.steps] == ["succeeded", "running", "pending"]
    assert gitlab.calls == 2  # la troisième étape n'a jamais atteint l'adaptateur
    plan = await stores.plans.get(project, record.id)
    assert plan is not None and plan.status == "dev_approved"  # jamais `executed`

    emitted = await events.read_after(project, 0)
    dump = json.dumps([e.model_dump(mode="json") for e in emitted]) + caplog.text
    assert "secret-adapter" not in dump and "glpat-" not in dump
    last = emitted[-1].data
    assert last.kind == "execution" and last.state == "blocked"
    assert [s.status for s in last.steps] == ["succeeded", "failed", "pending"]
    assert last.result is not None
    assert last.result.summary == "L'exécution est bloquée à l'étape 2. Rien d'autre n'a été lancé."


# --- Bail renouvelé pendant un appel long ; refus d'approbation ---------------------------------


class SteppedClock:
    """Horloge des dépôts : n'avance que quand le test le décide."""

    def __init__(self) -> None:
        self.now = datetime(2030, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def far_future() -> datetime:
    return datetime(2100, 1, 1, tzinfo=UTC)


def long_ago() -> datetime:
    return datetime(2000, 1, 1, tzinfo=UTC)


class SlowGateway:
    """Un appel long : ne rend la main que lorsque le test le libère."""

    idempotency_scope = ""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def call(self, call: GatewayCall) -> GatewayResult:
        self.entered.set()
        await self.release.wait()
        return GatewayResult(
            output={"group_id": 2000},
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


async def test_the_lease_is_renewed_during_a_long_call() -> None:
    catalog = load_catalog(environment="staging")
    clock = SteppedClock()
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(clock, projects)
    events = InMemoryEventLog()
    project = (await projects.create("p")).id
    draft = Draft(
        title="Groupe",
        summary="Un groupe",
        environment="staging",
        steps=[
            DraftStep(
                "Racine",
                "gitlab.create_group",
                {"parent_group_id": 1000, "name": "A", "path": "aa"},
            )
        ],
    )
    record, _ = await Planner(catalog, stores.plans, stores.registry, clock=far_future).propose(
        project, draft, DEV_USER_ID
    )
    approved = await ApprovalService(catalog, stores, events, dev_members()).approve(
        project, record.id, record.content_hash, DEV_PRINCIPAL
    )
    assert isinstance(approved, Approved)
    gateway = SlowGateway()
    engine = ExecutionEngine(
        catalog=catalog,
        stores=stores,
        gateway=gateway,
        events=events,
        lease_renew_interval_s=0.01,
    )
    task = asyncio.create_task(engine.run(project, approved.execution_id))
    await gateway.entered.wait()
    for _ in range(3):  # 90 s passent : sans renouvellement, le bail de 60 s serait expiré
        clock.now += timedelta(seconds=30)
        await asyncio.sleep(0.05)
    assert await stores.executions.claim_lease(approved.execution_id, "autre-moteur") is None
    gateway.release.set()
    await task
    execution = await stores.executions.get(project, approved.execution_id)
    assert execution is not None and execution.state == "succeeded"


async def test_a_refused_approval_reissues_the_plan_card_from_the_stored_state() -> None:
    catalog = load_catalog(environment="staging")
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    events = InMemoryEventLog()
    project = (await projects.create("p")).id
    draft = Draft(
        title="Groupe",
        summary="Un groupe",
        environment="staging",
        steps=[
            DraftStep(
                "Racine",
                "gitlab.create_group",
                {"parent_group_id": 1000, "name": "A", "path": "aa"},
            )
        ],
    )
    record, _ = await Planner(catalog, stores.plans, stores.registry, clock=long_ago).propose(
        project, draft, DEV_USER_ID
    )  # expiré
    refused = await ApprovalService(catalog, stores, events, dev_members()).approve(
        project, record.id, record.content_hash, DEV_PRINCIPAL
    )
    assert refused == ApprovalRefused("plan_not_approvable")
    cards = [e.data for e in await events.read_after(project, 0) if e.type == "card"]
    assert len(cards) == 1
    assert cards[0].kind == "plan" and cards[0].card_id == plan_card_id(record.id)
    assert (cards[0].status, cards[0].approvable) == ("expired", False)
    stored = await stores.plans.get(project, record.id)
    assert stored is not None and stored.status == "expired"  # écrit, plus seulement affiché


async def test_a_production_plan_waits_for_an_admin_who_then_starts_the_execution() -> None:
    """D2/D3 : la validation du développeur n'écrit aucune exécution (202) et émet la carte
    `pending` ; seul un admin approuve (le développeur reçoit `forbidden`, rien n'est écrit)."""
    catalog = load_catalog(environment="staging")
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    events = InMemoryEventLog()
    members = dev_members()
    project = (await projects.create("p")).id
    draft = Draft(
        title="Production",
        summary="Préparer le projet",
        environment="production",
        steps=[
            DraftStep(
                "Préparer",
                "server.apply_playbook",
                {
                    "environment": "production",
                    "project": "safe-eat",
                    "playbook": "bootstrap_project",
                    "mode": "apply",
                },
            )
        ],
    )
    record, _ = await Planner(catalog, stores.plans, stores.registry).propose(
        project, draft, DEV_USER_ID
    )
    service = ApprovalService(catalog, stores, events, members)
    pending = await service.approve(project, record.id, record.content_hash, DEV_PRINCIPAL)
    assert isinstance(pending, AwaitingAdmin)
    assert await stores.executions.list_resumable() == []  # aucune exécution n'a été créée

    card = [e.data for e in await events.read_after(project, 0) if e.data.kind == "approval"][-1]
    assert (card.status, card.rule_id, card.missing) == (  # type: ignore[union-attr]
        "pending",
        "R7-ecriture-production",
        ["admin_approved"],
    )
    assert card.approver_roles == ["team_admin", "org_admin"]  # type: ignore[union-attr]

    refused = await service.approve_admin(project, record.id, record.content_hash, DEV_PRINCIPAL)
    assert refused == ApprovalRefused("forbidden")
    assert not await stores.plans.has_admin_approval(record.id, record.content_hash)

    boss = Principal(user_id=DEV_USER_ID, name="boss", role="team_admin")
    approved = await service.approve_admin(project, record.id, record.content_hash, boss)
    assert isinstance(approved, Approved) and approved.created
    last = [e.data for e in await events.read_after(project, 0) if e.data.kind == "approval"][-1]
    assert (last.status, last.decided_by.name) == ("approved", "boss")  # type: ignore[union-attr]
