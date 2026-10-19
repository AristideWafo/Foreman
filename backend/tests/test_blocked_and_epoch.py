"""Exécution bloquée : cause lisible ; époque des faux : pas de rejeu périmé au redémarrage."""

from collections.abc import Mapping
from uuid import UUID

from pydantic import JsonValue

from foreman.core.approval import ApprovalService
from foreman.core.catalog import Catalog
from foreman.core.execution.engine import ExecutionEngine
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.planning import Draft, DraftStep, Planner
from foreman.core.ports import AdapterError, AdapterResult, ToolAdapter
from foreman.core.store import DEV_USER_ID, Approved, Stores
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer
from support import DEV_PRINCIPAL, dev_members

REF = {"$from": {"step": 1, "field": "group_id"}}


class RefusingSecondCall:
    """Le fournisseur refuse le second appel, avec un message chargé d'un détail interne."""

    def __init__(self, inner: ToolAdapter) -> None:
        self.inner, self.calls = inner, 0

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        self.calls += 1
        if self.calls == 2:
            raise AdapterError("groupe parent introuvable : 2000 (détail interne)")
        return await self.inner.execute(tool, params, idempotency_key)


def catalog() -> Catalog:
    return load_catalog(environment="staging")


def gitlab(first_group_id: int = 2000) -> SimulatedGitLab:
    return SimulatedGitLab.from_referentiel(
        catalog().referentiels["gitlab-groups"].data, first_group_id=first_group_id
    )


def engine_for(stores: Stores, events: InMemoryEventLog, adapter: ToolAdapter) -> ExecutionEngine:
    gateway = ToolGateway(
        catalog=catalog(),
        stores=stores,
        members=dev_members(),
        adapters={
            "gitlab": adapter,
            "server": SimulatedServer(),
            "dns": SimulatedDns.from_referentiel(catalog().referentiels["infra-staging"].data),
        },
    )
    return ExecutionEngine(catalog=catalog(), stores=stores, gateway=gateway, events=events)


async def run_plan(
    stores: Stores, events: InMemoryEventLog, engine: ExecutionEngine, project: UUID, child: str
) -> UUID:
    draft = Draft(
        title="Groupes",
        summary="Deux groupes",
        environment="staging",
        steps=[
            DraftStep(
                "Racine",
                "gitlab.create_group",
                {"parent_group_id": 1000, "name": "A", "path": "aa"},
            ),
            DraftStep(
                "Enfant",
                "gitlab.create_group",
                {"parent_group_id": REF, "name": child, "path": child},
            ),
        ],
    )
    record, _ = await Planner(catalog(), stores.plans).propose(project, draft, DEV_USER_ID)
    approved = await ApprovalService(catalog(), stores, events, dev_members()).approve(
        project, record.id, record.content_hash, DEV_PRINCIPAL
    )
    assert isinstance(approved, Approved)
    await engine.run(project, approved.execution_id)
    return approved.execution_id


async def test_a_blocked_card_says_why_without_internal_detail() -> None:
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    events = InMemoryEventLog()
    project = (await projects.create("p")).id
    engine = engine_for(stores, events, RefusingSecondCall(gitlab()))
    await run_plan(stores, events, engine, project, "bb")

    last = (await events.read_after(project, 0))[-1].data
    assert last.kind == "execution" and last.state == "blocked" and last.result is not None
    assert last.result.summary == (
        "L'exécution est bloquée à l'étape 2. "
        "Le fournisseur a refusé l'appel (état externe perdu ou indisponible). Relancez le plan."
    )


async def test_a_restarted_fake_does_not_replay_a_stale_step_result() -> None:
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    events = InMemoryEventLog()
    project = (await projects.create("p")).id
    await run_plan(stores, events, engine_for(stores, events, gitlab()), project, "bb")

    # « Redémarrage » : nouveau faux amnésique (autres ids), même base ; l'étape 1 a la même clé.
    second = await run_plan(stores, events, engine_for(stores, events, gitlab(3000)), project, "cc")

    execution = await stores.executions.get(project, second)
    assert execution is not None and execution.state == "succeeded"
    assert execution.steps[0].result is not None and execution.steps[0].result["group_id"] == 3000
