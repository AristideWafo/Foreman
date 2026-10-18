"""Tool Gateway : refus audités sans appel d'adaptateur, sortie filtrée, matrice minimale."""

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import JsonValue

from foreman.core.catalog import Catalog, PolicyMatrix, ToolClass, parse_policy
from foreman.core.gateway.errors import DENIED_MESSAGE, CallDenied
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.gateway.port import GatewayCall
from foreman.core.gateway.redact import MASK
from foreman.core.policy.matrix import (
    Allow,
    AllowIf,
    Deny,
    PolicyRequest,
    Verdict,
    evaluate,
)
from foreman.core.ports import AdapterResult, ToolAdapter
from foreman.core.store import DEV_USER_ID, Approved, NewPlan, NewResource, PlanRecord, Stores
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryProjectStore, in_memory_stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "catalog"
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
SECRET_TOKEN = "glpat-" + "A" * 24
SECRET_PASSWORD = "hunter2-hunter2"  # noqa: S105 - valeur factice
Step = dict[str, JsonValue]


# --- Fakes nommés -----------------------------------------------------------------------------


class CountingAdapter:
    """Enveloppe un faux : l'appel qui ne devait pas avoir lieu se voit dans `calls`."""

    def __init__(self, inner: ToolAdapter) -> None:
        self.inner = inner
        self.calls = 0

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        self.calls += 1
        return await self.inner.execute(tool, params, idempotency_key)


class LeakyAdapter:
    """Renvoie des secrets dans la sortie et dans ses logs, et beaucoup trop de texte."""

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        output: dict[str, JsonValue] = {
            "group_id": 2000,
            "web_url": "https://gitlab.example.org/foreman-demo/safe-eat",
            "owner_email": "dev@example.org",  # champ déclaré `redact` par le test
            "api_token": SECRET_TOKEN,  # nom de champ sensible
            "note": f"password={SECRET_PASSWORD} " + "x" * 800,
        }
        logs = [f"connexion avec {SECRET_TOKEN}", "y" * 900, *(f"ligne {i}" for i in range(120))]
        return AdapterResult(output=output, logs=logs)


# --- Banc -------------------------------------------------------------------------------------


def group_step(seq: int, parent: int, path: str) -> Step:
    return {
        "seq": seq,
        "tool": "gitlab.create_group",
        "params": {"parent_group_id": parent, "name": path.title(), "path": path},
        "idempotency_key": f"k-{seq}-{path}",
    }


def playbook_step(seq: int, playbook: str, environment: str = "staging") -> Step:
    return {
        "seq": seq,
        "tool": "server.apply_playbook",
        "params": {
            "environment": environment,
            "project": "safe-eat",
            "playbook": playbook,
            "mode": "apply",
        },
        "idempotency_key": f"k-{seq}-{playbook}",
    }


@dataclass
class World:
    catalog: Catalog
    stores: Stores
    projects: InMemoryProjectStore
    gitlab: CountingAdapter
    server: CountingAdapter
    gateway: ToolGateway


def make_world(catalog: Catalog | None = None, gitlab: ToolAdapter | None = None) -> World:
    catalog = catalog or load_catalog(CATALOG_ROOT, environment="staging")
    projects = InMemoryProjectStore()
    _, stores = in_memory_stores(projects=projects)
    gitlab_counter = CountingAdapter(
        gitlab or SimulatedGitLab.from_referentiel(catalog.referentiels["gitlab-groups"].data)
    )
    server_counter = CountingAdapter(SimulatedServer())
    dns = SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data)
    gateway = ToolGateway(
        catalog=catalog,
        stores=stores,
        adapters={"gitlab": gitlab_counter, "server": server_counter, "dns": dns},
    )
    return World(catalog, stores, projects, gitlab_counter, server_counter, gateway)


@dataclass(frozen=True)
class Started:
    project_id: UUID
    execution_id: UUID
    plan: PlanRecord


async def start(
    world: World, steps: list[Step], *, environment: str = "staging", project_id: UUID | None = None
) -> Started:
    """Un plan approuvé et son exécution, comme après un clic sur « Valider »."""
    project = project_id or (await world.projects.create("p")).id
    plan = await world.stores.plans.create(
        NewPlan(
            project_id=project,
            content={"environment": environment, "steps": steps},
            content_hash="sha256:" + "ab" * 32,
            skills_used=[],
            expires_at=FUTURE,
        )
    )
    approved = await world.stores.plans.approve(project, plan.id, plan.content_hash, DEV_USER_ID, 2)
    assert isinstance(approved, Approved)
    return Started(project, approved.execution_id, plan)


def call_for(started: Started, seq: int = 1, **changes: object) -> GatewayCall:
    """L'appel fidèle à l'étape `seq` du plan, sauf les champs modifiés."""
    steps = started.plan.content["steps"]
    step = next(s for s in steps if s["seq"] == seq)  # type: ignore[attr-defined, union-attr]
    base = GatewayCall(
        project_id=started.project_id,
        execution_id=started.execution_id,
        step_seq=seq,
        plan_hash=started.plan.content_hash,
        tool=step["tool"],
        params=step["params"],
        idempotency_key=step["idempotency_key"],
    )
    return replace(base, **changes)  # type: ignore[arg-type]


async def register(world: World, steps: list[Step], resource: NewResource) -> UUID:
    """Inscrit une ressource au registre d'un NOUVEAU projet (comme le ferait le moteur)."""
    started = await start(world, steps)
    store = world.stores.executions
    lease = await store.claim_lease(started.execution_id, "w1")
    assert lease is not None
    await store.reserve_idempotency(lease, 1)
    await store.complete_step(lease, 1, {}, [resource], [])
    return started.project_id


def with_tool(catalog: Catalog, name: str, **updates: object) -> Catalog:
    tool = catalog.tools[name].model_copy(update=updates)
    return replace(catalog, tools={**catalog.tools, name: tool})


# --- 1. Refus : adaptateur non appelé, une seule ligne d'audit « denied » ---------------------


@dataclass(frozen=True)
class Refusal:
    call: GatewayCall
    code: str
    adapter_calls: int = 0


Scenario = Callable[[], Awaitable[tuple[World, Refusal]]]


async def unknown_property() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [group_step(1, 1000, "safe-eat")])
    params = {**call_for(started).params, "force": True}
    return world, Refusal(call_for(started, params=params), "invalid_params")


async def call_differs_from_the_step() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [group_step(1, 1000, "safe-eat")])
    other = {**call_for(started).params, "path": "autre-chemin"}
    return world, Refusal(call_for(started, params=other), "call_differs_from_step")


async def hash_differs_from_the_plan() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [group_step(1, 1000, "safe-eat")])
    return world, Refusal(call_for(started, plan_hash="sha256:" + "0" * 64), "plan_hash_mismatch")


async def environment_differs_from_the_plan() -> tuple[World, Refusal]:
    base = load_catalog(CATALOG_ROOT, environment="staging")
    schema = copy.deepcopy(base.tools["server.apply_playbook"].input)
    schema["properties"]["environment"] = {"enum": ["staging", "production"]}  # type: ignore[index]
    world = make_world(with_tool(base, "server.apply_playbook", input=schema))
    started = await start(world, [playbook_step(1, "bootstrap_project", "production")])
    return world, Refusal(call_for(started), "environment_mismatch")


async def parent_belongs_to_another_project() -> tuple[World, Refusal]:
    world = make_world()
    owner = await register(
        world, [group_step(1, 1000, "safe-eat")], NewResource("gitlab", "gitlab_group", "2000")
    )
    assert owner  # le groupe 2000 est au registre du projet propriétaire, pas de l'intrus
    started = await start(world, [group_step(1, 2000, "backend")])
    return world, Refusal(call_for(started), "scope_violation")


async def target_is_not_in_the_registry() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [playbook_step(1, "deploy_compose")])
    return world, Refusal(call_for(started), "scope_violation")


async def write_outside_staging() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [group_step(1, 1000, "safe-eat")], environment="production")
    return world, Refusal(call_for(started), "policy_denied")


async def budget_is_spent() -> tuple[World, Refusal]:
    catalog = load_catalog(CATALOG_ROOT, environment="staging")
    budgets = catalog.policy.budgets.model_copy(
        update={
            "per_execution": catalog.policy.budgets.per_execution.model_copy(
                update={"max_tool_calls": 1}
            )
        }
    )
    world = make_world(
        replace(catalog, policy=catalog.policy.model_copy(update={"budgets": budgets}))
    )
    started = await start(world, [group_step(1, 1000, "safe-eat")])
    await world.gateway.call(call_for(started))  # le seul appel du budget
    return world, Refusal(call_for(started), "budget_exceeded", adapter_calls=1)


@pytest.mark.parametrize(
    "scenario",
    [
        unknown_property,
        call_differs_from_the_step,
        hash_differs_from_the_plan,
        environment_differs_from_the_plan,
        parent_belongs_to_another_project,
        target_is_not_in_the_registry,
        write_outside_staging,
        budget_is_spent,
    ],
)
async def test_a_refused_call_never_reaches_the_adapter_and_is_audited_once(
    scenario: Scenario,
) -> None:
    world, refusal = await scenario()
    with pytest.raises(CallDenied) as denied:
        await world.gateway.call(refusal.call)
    assert denied.value.code == refusal.code
    assert str(denied.value) == DENIED_MESSAGE  # opaque : ni paramètre ni cause
    assert world.gitlab.calls + world.server.calls == refusal.adapter_calls
    logged = await world.stores.audit.list_for_project(refusal.call.project_id)
    assert [(e.decision, e.result_redacted) for e in logged] == [("denied", {"code": refusal.code})]


# --- 2. Autorisé : sortie masquée et tronquée (R6) --------------------------------------------


async def test_an_allowed_call_returns_masked_and_truncated_output() -> None:
    catalog = with_tool(
        load_catalog(CATALOG_ROOT, environment="staging"),
        "gitlab.create_group",
        redact=["owner_email"],
    )
    world = make_world(catalog, gitlab=LeakyAdapter())
    started = await start(world, [group_step(1, 1000, "safe-eat")])

    result = await world.gateway.call(call_for(started))

    assert len(result.logs) <= 50 and all(len(line) <= 500 for line in result.logs)
    assert result.output["owner_email"] == MASK
    assert result.output["api_token"] == MASK
    note = result.output["note"]
    assert isinstance(note, str) and len(note) <= 500
    leaked = repr(result.output) + repr(result.logs) + repr(result.audit)
    assert SECRET_TOKEN not in leaked and SECRET_PASSWORD not in leaked
    assert result.audit.decision == "allow"
    assert result.audit.rule_id == "R6-ecriture-staging"
    assert result.resources == (
        NewResource(
            "gitlab", "gitlab_group", "2000", "https://gitlab.example.org/foreman-demo/safe-eat"
        ),
    )
    assert await world.stores.audit.list_for_project(started.project_id) == []  # écrit avec l'étape


# --- 3. Matrice minimale ----------------------------------------------------------------------


def minimal_matrix() -> PolicyMatrix:
    return parse_policy((CATALOG_ROOT / "policy" / "matrix.yaml").read_bytes(), "matrix.yaml")


def request(
    tool_class: ToolClass,
    *,
    environment: str = "staging",
    reversibility: str = "reversible",
    role: str = "developer",
    level: int = 2,
) -> PolicyRequest:
    return PolicyRequest(
        tool_class=tool_class,
        environment=environment,
        reversibility=reversibility,  # type: ignore[arg-type]
        role=role,
        level=level,
    )


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        (request("read", reversibility="not_applicable", level=1), Allow("R1-lecture")),
        (request("control", reversibility="not_applicable"), Allow("R2-controle")),
        (
            request("write_registry", reversibility="compensable"),
            AllowIf("R6-ecriture-staging", ("plan_approved",)),
        ),
        (request("write_registry", level=1), Deny("level_too_low", "R6-ecriture-staging")),
        (request("write_registry", role="viewer"), Deny("role_not_allowed", "R6-ecriture-staging")),
        (request("write_registry", reversibility="irreversible"), Deny("no_rule")),
        (request("write_foreign"), Deny("no_rule")),
        (request("destructive"), Deny("no_rule")),
        (request("write_registry", environment="production"), Deny("unknown_environment")),
    ],
)
def test_the_minimal_matrix_allows_only_what_it_names(
    asked: PolicyRequest, expected: Verdict
) -> None:
    assert evaluate(minimal_matrix(), asked) == expected
