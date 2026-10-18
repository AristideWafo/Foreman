"""Tool Gateway : refus audités sans appel d'adaptateur, échecs opaques, sortie filtrée, matrice."""

import asyncio
import base64
import contextlib
import copy
import signal
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import JsonValue

import foreman.core.gateway.redact as redact_module
from foreman.core.catalog import Catalog, PolicyMatrix, ToolClass, parse_policy
from foreman.core.gateway.errors import DENIED_MESSAGE, FAILED_MESSAGE, CallDenied, CallFailed
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.gateway.port import GatewayCall
from foreman.core.gateway.redact import (
    ALL_PATTERNS,
    MASK,
    filter_logs,
    mask_text,
    redact_value,
)
from foreman.core.policy.matrix import (
    Allow,
    AllowIf,
    Deny,
    PolicyRequest,
    Verdict,
    evaluate,
)
from foreman.core.ports import AdapterResult, ForeignResource, ToolAdapter
from foreman.core.references import resolve_params
from foreman.core.store import (
    DEV_USER_ID,
    Approved,
    AuditEntry,
    Lease,
    NewPlan,
    NewResource,
    PlanRecord,
    ResourceRecord,
    Stores,
)
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryProjectStore, MemoryState, in_memory_stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "catalog"
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
SECRET_TOKEN = "glpat-" + "A" * 24
SECRET_PASSWORD = "hunter2-hunter2"  # noqa: S105 - valeur factice
SECRET_URL = "postgres://admin:" + "TOP-SECRET-PW" + "@db.internal/foreman"
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
            "web_url": f"https://oauth2:{SECRET_TOKEN}@gitlab.example.org/foreman-demo/safe-eat?t=1",
            "owner_email": "dev@example.org",  # champ déclaré `redact` par le test
            "api_token": "valeur-ordinaire",  # masquée par le NOM du champ, pas par motif
            "client_secret": "autre-valeur-ordinaire",
            "note": f"password={SECRET_PASSWORD} " + "x" * 800,
        }
        logs = [f"connexion avec {SECRET_TOKEN}", "y" * 900, *(f"ligne {i}" for i in range(120))]
        return AdapterResult(output=output, logs=logs)


class BigAdapter:
    """Crée le groupe 2000 mais renvoie une sortie bien trop grande."""

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        blob: list[JsonValue] = [f"enregistrement-{i}" for i in range(2000)]
        return AdapterResult(
            output={"group_id": 2000, "web_url": "https://g.example/x", "dump": blob}
        )


class GatedAdapter:
    """Reste dans `execute` jusqu'à ce que le test le libère."""

    def __init__(self) -> None:
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return AdapterResult(output={"group_id": 2000, "web_url": "https://g.example/x"})


class SlowAdapter:
    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        await asyncio.sleep(3)
        return AdapterResult(output={})


class DefectiveAdapter:
    """Lève une exception inattendue dont le message contient un secret."""

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        raise RuntimeError(f"connexion refusée vers {SECRET_URL}")


class ForeignAdapter:
    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        raise ForeignResource(f"existe déjà : {SECRET_URL}")


class MalformedAdapter:
    """Renvoie un résultat qui n'a pas la forme du port (ensemble, octets, entier dans les logs)."""

    def __init__(self, output: Any, logs: Any) -> None:
        self._output, self._logs = output, logs

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        return AdapterResult(output=self._output, logs=self._logs)


class ExplodingRegistry:
    """Registre en panne : l'exception porte une adresse avec identifiants."""

    async def contains(self, *args: object) -> bool:
        raise RuntimeError(SECRET_URL)

    async def exists_elsewhere(self, *args: object) -> bool:
        raise RuntimeError(SECRET_URL)

    async def list_for_project(self, project_id: UUID) -> list[ResourceRecord]:
        return []


class ExplodingAudit:
    """Journal d'audit en panne : l'exception porte une adresse avec identifiants."""

    def __init__(self, inner: Any = None) -> None:
        self._inner = inner

    async def append(self, entry: AuditEntry) -> None:
        raise RuntimeError(SECRET_URL)

    async def list_for_project(self, project_id: UUID, limit: int = 200) -> list[AuditEntry]:
        return []


class FlakyAudit:
    """La première écriture échoue (panne passagère), les suivantes passent."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._failed = False

    async def append(self, entry: AuditEntry) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError(SECRET_URL)
        await self._inner.append(entry)

    async def list_for_project(self, project_id: UUID, limit: int = 200) -> list[AuditEntry]:
        return await self._inner.list_for_project(project_id, limit)


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- Banc -------------------------------------------------------------------------------------


def group_step(seq: int, parent: JsonValue, path: str) -> Step:
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


def health_step(seq: int) -> Step:
    params: dict[str, JsonValue] = {"environment": "staging", "project": "safe-eat"}
    return {
        "seq": seq,
        "tool": "server.healthcheck",
        "params": params,
        "idempotency_key": f"k-{seq}",
    }


FROM_STEP_1: dict[str, JsonValue] = {"$from": {"step": 1, "field": "group_id"}}


@dataclass
class World:
    catalog: Catalog
    stores: Stores
    state: MemoryState
    projects: InMemoryProjectStore
    gitlab: CountingAdapter
    server: CountingAdapter
    gateway: ToolGateway


def make_world(
    catalog: Catalog | None = None,
    gitlab: ToolAdapter | None = None,
    registry: object | None = None,
    clock: Callable[[], float] | None = None,
    audit: Callable[[Any], Any] | None = None,
) -> World:
    catalog = catalog or load_catalog(CATALOG_ROOT, environment="staging")
    projects = InMemoryProjectStore()
    state, stores = in_memory_stores(projects=projects)
    if registry is not None:
        stores = replace(stores, registry=registry)  # type: ignore[type-var]
    if audit is not None:
        stores = replace(stores, audit=audit(stores.audit))
    gitlab_counter = CountingAdapter(
        gitlab or SimulatedGitLab.from_referentiel(catalog.referentiels["gitlab-groups"].data)
    )
    server_counter = CountingAdapter(SimulatedServer())
    dns = SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data)
    options: dict[str, Any] = {} if clock is None else {"clock": clock}
    gateway = ToolGateway(
        catalog=catalog,
        stores=stores,
        adapters={"gitlab": gitlab_counter, "server": server_counter, "dns": dns},
        **options,
    )
    return World(catalog, stores, state, projects, gitlab_counter, server_counter, gateway)


@dataclass(frozen=True)
class Started:
    project_id: UUID
    execution_id: UUID
    plan: PlanRecord
    lease: Lease


async def start(
    world: World,
    steps: list[Step],
    *,
    environment: str = "staging",
    project_id: UUID | None = None,
    reserve: tuple[int, ...] = (1,),
) -> Started:
    """Un plan approuvé, son exécution, le bail du « moteur » et les étapes réservées."""
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
    lease = await world.stores.executions.claim_lease(approved.execution_id, "w1")
    assert lease is not None
    for seq in reserve:
        await world.stores.executions.reserve_idempotency(lease, seq)
    return Started(project, approved.execution_id, plan, lease)


def call_for(started: Started, seq: int = 1, **changes: object) -> GatewayCall:
    """L'appel fidèle à l'étape `seq` du plan, sauf les champs modifiés."""
    steps: Any = started.plan.content["steps"]
    step = next(s for s in steps if s["seq"] == seq)
    base = GatewayCall(
        project_id=started.project_id,
        execution_id=started.execution_id,
        step_seq=seq,
        plan_hash=started.plan.content_hash,
        tool=step["tool"],
        params=step["params"],
        idempotency_key=step["idempotency_key"],
        lease_owner=started.lease.owner,
        lease_epoch=started.lease.epoch,
    )
    return replace(base, **changes)  # type: ignore[arg-type]


async def succeed(
    world: World, started: Started, seq: int, result: dict[str, object], reserve: bool = False
) -> None:
    store = world.stores.executions
    if reserve:
        await store.reserve_idempotency(started.lease, seq)
    await store.complete_step(started.lease, seq, result, [], [])


async def engine_step(world: World, started: Started, seq: int) -> None:
    """Ce que fera le moteur : réserver, résoudre les `$from`, appeler, écrire étape + audit."""
    store = world.stores.executions
    execution = await store.get(started.project_id, started.execution_id)
    assert execution is not None
    outputs: Any = {s.seq: s.result for s in execution.steps if s.status == "succeeded"}
    step = next(s for s in execution.steps if s.seq == seq)
    await store.reserve_idempotency(started.lease, seq)
    params = resolve_params(step.params, outputs, seq)  # type: ignore[arg-type]
    result = await world.gateway.call(call_for(started, seq, params=params))
    await store.complete_step(
        started.lease, seq, result.output, list(result.resources), [result.audit]
    )


async def register(world: World, steps: list[Step], resource: NewResource) -> UUID:
    """Inscrit une ressource au registre d'un NOUVEAU projet (comme le ferait le moteur)."""
    started = await start(world, steps)
    await world.stores.executions.complete_step(started.lease, 1, {}, [resource], [])
    return started.project_id


def with_tool(catalog: Catalog, name: str, **updates: object) -> Catalog:
    tool = catalog.tools[name].model_copy(update=updates)
    return replace(catalog, tools={**catalog.tools, name: tool})


def with_policy(catalog: Catalog, **updates: object) -> Catalog:
    return replace(catalog, policy=catalog.policy.model_copy(update=updates))


def base_catalog() -> Catalog:
    return load_catalog(CATALOG_ROOT, environment="staging")


# --- 1. Refus : adaptateur non appelé, une seule ligne d'audit « denied » ---------------------


@dataclass(frozen=True)
class Refusal:
    call: GatewayCall
    code: str
    adapter_calls: int = 0
    rows: tuple[str, ...] = ("denied",)  # décisions auditées pour ce projet, dans l'ordre


Scenario = Callable[[], Awaitable[tuple[World, Refusal]]]
ONE_GROUP = [group_step(1, 1000, "safe-eat")]


async def unknown_property() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    params = {**call_for(started).params, "force": True}
    return world, Refusal(call_for(started, params=params), "invalid_params")


async def call_differs_from_the_step() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    other = {**call_for(started).params, "path": "autre-chemin"}
    return world, Refusal(call_for(started, params=other), "call_differs_from_step")


async def key_differs_from_the_step() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started, idempotency_key="autre-cle"), "call_differs_from_step")


async def tool_differs_from_the_step() -> tuple[World, Refusal]:
    """Mêmes paramètres, même clé, autre outil (dont le schéma accepte ces paramètres)."""
    base = base_catalog()
    lookalike = with_tool(base, "server.healthcheck", input=base.tools["dns.list_records"].input)
    world = make_world(lookalike)
    params: dict[str, JsonValue] = {"environment": "staging"}
    dns_step: Step = {
        "seq": 1,
        "tool": "dns.list_records",
        "params": params,
        "idempotency_key": "k",
    }
    started = await start(world, [dns_step])
    return world, Refusal(call_for(started, tool="server.healthcheck"), "call_differs_from_step")


async def reference_has_no_value() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(
        world, [group_step(1, 1000, "safe-eat"), group_step(2, FROM_STEP_1, "xx")]
    )
    await succeed(world, started, 1, {})  # l'étape 1 n'a produit aucun `group_id`
    await world.stores.executions.reserve_idempotency(started.lease, 2)
    params = {"parent_group_id": 2000, "name": "Xx", "path": "xx"}
    return world, Refusal(call_for(started, 2, params=params), "call_differs_from_step")


async def hash_differs_from_the_plan() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started, plan_hash="sha256:" + "0" * 64), "plan_hash_mismatch")


async def plan_is_not_approved() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    entry = world.state.plans[started.plan.id]
    entry.record = replace(entry.record, status="invalidated")
    return world, Refusal(call_for(started), "plan_not_approved")


async def execution_of_another_project() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    stranger = (await world.projects.create("autre")).id
    return world, Refusal(call_for(started, project_id=stranger), "unknown_context")


async def execution_is_finished() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    await world.stores.executions.finish(started.lease, "blocked")
    return world, Refusal(call_for(started), "unknown_context")


async def unknown_tool() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started, tool="shell.run"), "unknown_tool")


async def lease_is_not_the_callers() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started, lease_epoch=started.lease.epoch + 1), "stale_lease")


async def succeeded_step_is_replayed() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP)
    await succeed(world, started, 1, {"group_id": 2000})
    return world, Refusal(call_for(started), "step_not_ready")


async def previous_step_is_pending() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(
        world, [group_step(1, 1000, "safe-eat"), group_step(2, 1000, "autre")], reserve=(1, 2)
    )
    return world, Refusal(call_for(started, 2), "step_not_ready")


async def step_was_never_reserved() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP, reserve=())
    return world, Refusal(call_for(started), "step_not_ready")


async def environment_differs_from_the_plan() -> tuple[World, Refusal]:
    base = base_catalog()
    schema = copy.deepcopy(base.tools["server.apply_playbook"].input)
    schema["properties"]["environment"] = {"enum": ["staging", "production"]}  # type: ignore[index]
    world = make_world(with_tool(base, "server.apply_playbook", input=schema))
    started = await start(world, [playbook_step(1, "bootstrap_project", "production")])
    return world, Refusal(call_for(started), "environment_mismatch")


async def parent_belongs_to_another_project() -> tuple[World, Refusal]:
    world = make_world()
    await register(world, ONE_GROUP, NewResource("gitlab", "gitlab_group", "2000"))
    started = await start(world, [group_step(1, 2000, "backend")])
    return world, Refusal(call_for(started), "scope_violation")


async def slug_belongs_to_another_project() -> tuple[World, Refusal]:
    world = make_world()
    await register(
        world,
        [playbook_step(1, "bootstrap_project")],
        NewResource("server", "server_project", "safe-eat"),
    )
    started = await start(world, [playbook_step(1, "bootstrap_project")])
    return world, Refusal(call_for(started), "scope_violation")


async def target_is_not_in_the_registry() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, [playbook_step(1, "deploy_compose")])
    return world, Refusal(call_for(started), "scope_violation")


async def write_outside_staging() -> tuple[World, Refusal]:
    world = make_world()
    started = await start(world, ONE_GROUP, environment="production")
    return world, Refusal(call_for(started), "policy_denied")


async def level_is_capped_by_the_environment() -> tuple[World, Refusal]:
    base = base_catalog()
    capped = base.policy.autonomy.environments["staging"].model_copy(update={"max_level": 1})
    autonomy = base.policy.autonomy.model_copy(update={"environments": {"staging": capped}})
    world = make_world(with_policy(base, autonomy=autonomy))
    started = await start(
        world, ONE_GROUP
    )  # niveau 2 demandé, R6 exige 2, l'environnement plafonne à 1
    return world, Refusal(call_for(started), "policy_denied")


async def environment_requires_an_administrator() -> tuple[World, Refusal]:
    base = base_catalog()
    strict = base.policy.autonomy.environments["staging"].model_copy(
        update={"admin_approval_required": True}
    )
    autonomy = base.policy.autonomy.model_copy(update={"environments": {"staging": strict}})
    world = make_world(with_policy(base, autonomy=autonomy))
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started), "policy_denied")


async def requirement_cannot_be_met() -> tuple[World, Refusal]:
    base = base_catalog()
    rules = [
        r.model_copy(update={"requires": [*r.requires, "admin_approved"]})
        if r.id == "R6-ecriture-staging"
        else r
        for r in base.policy.rules
    ]
    world = make_world(with_policy(base, rules=rules))
    started = await start(world, ONE_GROUP)
    return world, Refusal(call_for(started), "policy_denied")


def tight_budget(**updates: int) -> Catalog:
    base = base_catalog()
    per_execution = base.policy.budgets.per_execution.model_copy(update=updates)
    return with_policy(
        base, budgets=base.policy.budgets.model_copy(update={"per_execution": per_execution})
    )


async def call_budget_is_spent() -> tuple[World, Refusal]:
    world = make_world(tight_budget(max_tool_calls=1))
    started = await start(world, ONE_GROUP)
    await world.gateway.call(call_for(started))  # le seul appel du budget
    return world, Refusal(call_for(started), "budget_exceeded", 1, ("allow", "denied"))


async def time_budget_is_spent() -> tuple[World, Refusal]:
    clock = ManualClock()
    world = make_world(tight_budget(max_minutes=1), clock=clock)
    started = await start(world, ONE_GROUP)
    await world.gateway.call(call_for(started))
    clock.now = 3600.0  # une heure plus tard, pour une minute de budget
    return world, Refusal(call_for(started), "budget_exceeded", 1, ("allow", "denied"))


@pytest.mark.parametrize(
    "scenario",
    [
        unknown_property,
        call_differs_from_the_step,
        key_differs_from_the_step,
        tool_differs_from_the_step,
        reference_has_no_value,
        hash_differs_from_the_plan,
        plan_is_not_approved,
        execution_of_another_project,
        execution_is_finished,
        unknown_tool,
        lease_is_not_the_callers,
        succeeded_step_is_replayed,
        previous_step_is_pending,
        step_was_never_reserved,
        environment_differs_from_the_plan,
        parent_belongs_to_another_project,
        slug_belongs_to_another_project,
        target_is_not_in_the_registry,
        write_outside_staging,
        level_is_capped_by_the_environment,
        environment_requires_an_administrator,
        requirement_cannot_be_met,
        call_budget_is_spent,
        time_budget_is_spent,
    ],
)
async def test_a_refused_call_never_reaches_the_adapter_and_is_audited(scenario: Scenario) -> None:
    world, refusal = await scenario()
    with pytest.raises(CallDenied) as denied:
        await world.gateway.call(refusal.call)
    assert denied.value.code == refusal.code
    assert str(denied.value) == DENIED_MESSAGE  # opaque : ni paramètre ni cause
    assert world.gitlab.calls + world.server.calls == refusal.adapter_calls
    logged = await world.stores.audit.list_for_project(refusal.call.project_id)
    assert tuple(e.decision for e in logged) == refusal.rows
    assert logged[-1].result_redacted == {"code": refusal.code}
    if refusal.code == "unknown_context":
        assert logged[-1].execution_id is None  # ne se rattache à aucune exécution réelle


# --- 2. Exécution réelle : chaîne de bout en bout avec le « moteur » --------------------------


async def test_a_full_plan_runs_through_the_gateway_with_resolved_references() -> None:
    """Création, référence `$from`, puis préparation et déploiement : `deploy_compose` ne
    réinscrit pas le projet déjà inscrit par `bootstrap_project` (sinon `DuplicateResource`)."""
    world = make_world()
    steps = [
        group_step(1, 1000, "safe-eat"),
        group_step(2, FROM_STEP_1, "backend"),
        playbook_step(3, "bootstrap_project"),
        playbook_step(4, "deploy_compose"),
        health_step(5),
    ]
    started = await start(world, steps, reserve=())
    for seq in range(1, 6):
        await engine_step(world, started, seq)
    await world.stores.executions.finish(started.lease, "succeeded")

    gitlab: Any = world.gitlab.inner
    assert any(g.path == "backend" and g.parent_id == 2000 for g in gitlab.groups.values())
    registered = await world.stores.registry.list_for_project(started.project_id)
    assert sorted((r.resource_type, r.external_id) for r in registered) == [
        ("gitlab_group", "2000"),
        ("gitlab_group", "2001"),
        ("server_project", "safe-eat"),
    ]
    audit = await world.stores.audit.list_for_project(started.project_id)
    assert [e.decision for e in audit].count("allow") == 5
    assert [e.decision for e in audit].count("executed") == 5


# --- 3. Autorisé : sortie masquée et tronquée (R6) --------------------------------------------


async def test_an_allowed_call_returns_masked_and_truncated_output() -> None:
    catalog = with_tool(base_catalog(), "gitlab.create_group", redact=["owner_email"])
    world = make_world(catalog, gitlab=LeakyAdapter())
    started = await start(world, ONE_GROUP)

    result = await world.gateway.call(call_for(started))

    assert len(result.logs) <= 50 and all(len(line) <= 500 for line in result.logs)
    assert result.output["owner_email"] == MASK
    assert result.output["api_token"] == result.output["client_secret"] == MASK
    note = result.output["note"]
    assert isinstance(note, str) and len(note) <= 500
    leaked = repr(result.output) + repr(result.logs) + repr(result.audit)
    assert SECRET_TOKEN not in leaked and SECRET_PASSWORD not in leaked
    assert (result.audit.decision, result.audit.rule_id) == ("executed", "R6-ecriture-staging")
    # L'URL de la ressource perd ses identifiants et ses paramètres.
    assert result.resources == (
        NewResource(
            "gitlab", "gitlab_group", "2000", "https://gitlab.example.org/foreman-demo/safe-eat"
        ),
    )
    # La décision est auditée avant l'exécution ; le résultat s'écrit avec l'étape.
    logged = await world.stores.audit.list_for_project(started.project_id)
    assert [e.decision for e in logged] == ["allow"]


async def test_an_oversized_output_is_truncated_but_the_created_resource_is_kept() -> None:
    world = make_world(gitlab=BigAdapter())
    started = await start(world, ONE_GROUP)
    result = await world.gateway.call(call_for(started))
    assert result.output["truncated"] is True and result.output["group_id"] == 2000
    assert "dump" not in result.output
    assert [r.external_id for r in result.resources] == ["2000"]


# --- 4. Échecs : opaques, audités, rien d'attaché à l'exception -------------------------------


@dataclass(frozen=True)
class Failure:
    world: World
    started: Started
    code: str
    rows: tuple[str, ...]


async def adapter_times_out() -> Failure:
    catalog = with_tool(base_catalog(), "gitlab.create_group", timeout_s=0.05)
    world = make_world(catalog, gitlab=SlowAdapter())
    return Failure(world, await start(world, ONE_GROUP), "timeout", ("allow", "error"))


async def adapter_raises_a_secret() -> Failure:
    world = make_world(gitlab=DefectiveAdapter())
    return Failure(world, await start(world, ONE_GROUP), "adapter_defect", ("allow", "error"))


async def adapter_meets_a_foreign_resource() -> Failure:
    world = make_world(gitlab=ForeignAdapter())
    return Failure(world, await start(world, ONE_GROUP), "foreign_resource", ("allow", "error"))


async def adapter_returns_a_set() -> Failure:
    world = make_world(gitlab=MalformedAdapter({"group_id": {1, 2}}, []))
    return Failure(world, await start(world, ONE_GROUP), "invalid_output", ("allow", "error"))


async def adapter_returns_nan() -> Failure:
    world = make_world(gitlab=MalformedAdapter({"group_id": 2000, "ratio": float("nan")}, []))
    return Failure(world, await start(world, ONE_GROUP), "invalid_output", ("allow", "error"))


async def adapter_returns_bytes() -> Failure:
    world = make_world(gitlab=MalformedAdapter({"group_id": b"2000"}, []))
    return Failure(world, await start(world, ONE_GROUP), "invalid_output", ("allow", "error"))


async def adapter_logs_an_integer() -> Failure:
    world = make_world(gitlab=MalformedAdapter({"group_id": 2000}, ["ok", 42]))
    return Failure(world, await start(world, ONE_GROUP), "invalid_output", ("allow", "error"))


async def adapter_returns_a_group_of_another_project() -> Failure:
    """GitLab « retrouve » le groupe d'un autre projet : la ressource n'est pas adoptée."""
    world = make_world(gitlab=MalformedAdapter({"group_id": 2000}, []))
    await register(world, ONE_GROUP, NewResource("gitlab", "gitlab_group", "2000"))
    return Failure(world, await start(world, ONE_GROUP), "foreign_resource", ("allow", "error"))


async def registry_is_down() -> Failure:
    world = make_world(registry=ExplodingRegistry())
    started = await start(world, [group_step(1, 2000, "backend")])  # parent hors racine
    return Failure(world, started, "internal_error", ("error",))


@pytest.mark.parametrize(
    "scenario",
    [
        adapter_times_out,
        adapter_raises_a_secret,
        adapter_meets_a_foreign_resource,
        adapter_returns_a_set,
        adapter_returns_nan,
        adapter_returns_bytes,
        adapter_logs_an_integer,
        adapter_returns_a_group_of_another_project,
        registry_is_down,
    ],
)
async def test_a_failed_call_is_opaque_and_audited(
    scenario: Callable[[], Awaitable[Failure]],
) -> None:
    failure = await scenario()
    with pytest.raises(CallFailed) as raised:
        await failure.world.gateway.call(call_for(failure.started))
    error = raised.value
    assert error.code == failure.code and str(error) == FAILED_MESSAGE
    assert error.__cause__ is None and error.__context__ is None  # rien de l'exception d'origine
    logged = await failure.world.stores.audit.list_for_project(failure.started.project_id)
    assert tuple(e.decision for e in logged) == failure.rows
    assert logged[-1].result_redacted == {"code": failure.code}
    assert "TOP-SECRET-PW" not in repr(logged)


async def test_a_failing_audit_never_leaks_its_error_through_a_refusal() -> None:
    world = make_world(audit=ExplodingAudit)
    started = await start(world, ONE_GROUP)
    with pytest.raises(CallDenied) as denied:
        await world.gateway.call(call_for(started, plan_hash="sha256:" + "0" * 64))
    assert denied.value.code == "plan_hash_mismatch"
    assert denied.value.__cause__ is None and denied.value.__context__ is None
    assert "TOP-SECRET-PW" not in repr(denied.value.args)


async def test_a_call_not_executed_for_lack_of_an_audit_row_is_not_counted_in_the_budget() -> None:
    world = make_world(tight_budget(max_tool_calls=1), audit=FlakyAudit)
    started = await start(world, ONE_GROUP)
    with pytest.raises(CallFailed):  # la ligne `allow` n'a pas pu être écrite : rien ne s'exécute
        await world.gateway.call(call_for(started))
    assert world.gitlab.calls == 0
    assert (await world.gateway.call(call_for(started))).output["group_id"] == 2000


async def test_audited_parameters_are_masked_in_refusals_and_decisions() -> None:
    secret = f"{PWD.lower()}={VALUE}"  # un nom de groupe valide pour le schéma, mais un secret
    steps = [
        group_step(1, 1000, "safe-eat") | {"params": {**ONE_GROUP[0]["params"], "name": secret}}
    ]  # type: ignore[dict-item]
    world = make_world()
    started = await start(world, steps)
    with pytest.raises(CallDenied):
        await world.gateway.call(call_for(started, plan_hash="sha256:" + "0" * 64))
    executed = await world.gateway.call(call_for(started))
    logged = await world.stores.audit.list_for_project(started.project_id)
    assert [e.decision for e in logged] == ["denied", "allow"]
    assert all(e.params_redacted is not None for e in [*logged, executed.audit])
    assert VALUE not in repr(logged) + repr(executed.audit)


async def test_a_dry_run_registers_nothing_and_unlocks_no_deployment() -> None:
    check = playbook_step(1, "bootstrap_project")
    check["params"] = {**check["params"], "mode": "check"}  # type: ignore[dict-item]
    world = make_world()
    started = await start(world, [check, playbook_step(2, "deploy_compose")], reserve=())
    await engine_step(world, started, 1)
    assert await world.stores.registry.list_for_project(started.project_id) == []
    await world.stores.executions.reserve_idempotency(started.lease, 2)
    with pytest.raises(CallDenied) as denied:
        await world.gateway.call(call_for(started, 2))
    assert denied.value.code == "scope_violation"  # le projet n'a jamais été créé


# --- 5. Concurrence et annulation -------------------------------------------------------------


async def test_two_simultaneous_calls_for_one_step_execute_once() -> None:
    adapter = GatedAdapter()
    world = make_world(gitlab=adapter)
    started = await start(world, ONE_GROUP)
    first = asyncio.create_task(world.gateway.call(call_for(started)), name="premier-appel")
    await asyncio.wait_for(adapter.entered.wait(), timeout=5)
    with pytest.raises(CallDenied) as second:
        await world.gateway.call(call_for(started))
    assert second.value.code == "call_in_progress"
    adapter.release.set()
    assert (await asyncio.wait_for(first, timeout=5)).output["group_id"] == 2000
    assert adapter.calls == 1


async def test_a_cancelled_call_leaves_its_decision_and_its_outcome_in_the_audit() -> None:
    adapter = GatedAdapter()
    world = make_world(gitlab=adapter)
    started = await start(world, ONE_GROUP)
    task = asyncio.create_task(world.gateway.call(call_for(started)), name="appel-annule")
    await asyncio.wait_for(adapter.entered.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    logged = await world.stores.audit.list_for_project(started.project_id)
    assert [(e.decision, e.result_redacted) for e in logged] == [
        ("allow", None),
        ("error", {"code": "cancelled"}),
    ]


# --- 6. Masquage des secrets ------------------------------------------------------------------

# Les valeurs factices sont assemblées à l'exécution : aucun motif de secret dans le source.
PWD = "PASS" + "WORD"
TOK = "TO" + "KEN"
KEY = "ke" + "y"
AUTH = "Authori" + "zation"
BEARER = "Bear" + "er"
AT = "@"
CURL = "cur" + "l"
VALUE = "s3cr3t" + "Value" + "123456"
BASIC = base64.b64encode(b"utilisateur:" + b"motdepasse").decode()
PGP = [
    "-----BEGIN PGP PRIV" + "ATE KEY BLOCK-----",
    "corps",
    "-----END PGP PRIV" + "ATE KEY BLOCK-----",
]
PEM = [
    "-----BEGIN RSA PRIV" + "ATE KEY-----",
    "MIIEowIBAAKCAQEAsecretbody",
    "-----END RSA PRIV" + "ATE KEY-----",
]


@pytest.mark.parametrize(
    ("lines", "secret", "kept"),
    [
        ([f"POSTGRES_{PWD}={VALUE}"], VALUE, ""),
        ([f"export DEPLOY_{TOK}={VALUE}"], VALUE, ""),
        ([f'{{"access_{KEY}": "{VALUE}"}}'], VALUE, ""),
        ([f"Cookie: session={VALUE}; Path=/"], VALUE, ""),
        ([f"{AUTH}: {BEARER} {VALUE}"], VALUE, ""),
        ([f"{AUTH}: Basic {BASIC}"], BASIC, ""),
        ([f"header Basic {BASIC}"], BASIC, "header"),
        (["clone avec " + "github" + "_pat_" + "A1" * 20], "A1A1A1A1", "clone"),
        (["jeton " + "glcbt" + "-" + "B2" * 12], "B2B2B2B2", "jeton"),
        ([f"clone https://user:pa{AT}ss{AT}host.example/repo.git"], f"pa{AT}ss", "https://"),
        ([f"clone https://user:{'p' * 300}{AT}host.example/r.git"], "p" * 20, "host.example"),
        ([f'{{"{PWD.lower()}": "correct horse {VALUE}"}}'], VALUE, ""),
        ([f'DB_{PWD}="alpha {VALUE}"'], VALUE, ""),
        ([f'{{"{PWD.lower()}":"ab\\"{VALUE}"}}'], VALUE, ""),
        ([f"{PWD.lower()}=abc;{VALUE}"], VALUE, ""),
        ([f"{CURL} -u admin:{VALUE} https://x.example"], VALUE, "https://x.example"),
        ([f"{CURL} --user admin:{VALUE}"], VALUE, CURL),
        ([f"helm registry login reg.example -u a -p {VALUE}"], VALUE, ""),
        ([f"dock{'er'} login -u admin -p {VALUE} reg.example"], VALUE, ""),
        ([f"{'x' * 60}_{PWD}={VALUE}"], VALUE, ""),
        ([f"{PWD}{' ' * 30}= {VALUE}"], VALUE, ""),
        (
            [f"{PEM[0]} a {PEM[2]} milieu {PEM[0]}", f"corps {VALUE}", PEM[2], "apres"],
            VALUE,
            "apres",
        ),
        ([f"mysql --{PWD.lower()} {VALUE} --verbose"], VALUE, "--verbose"),
        ([f"mysql -u root -p{VALUE}"], VALUE, ""),
        ([f"MYSQL_ROOT_{PWD} {VALUE}"], VALUE, ""),
        ([f"secret_key_base {VALUE}"], VALUE, ""),
        ([f"{PWD.lower()}: >-", f"  {VALUE}", "  suite", "autre: ok"], VALUE, "autre: ok"),
        ([PGP[0], f"corps {VALUE}", PGP[2], "apres"], VALUE, "apres"),
        (["x" * 3000 + PGP[0], f"corps {VALUE}", PGP[2], "apres"], VALUE, "apres"),
        ([f"clone https://user:{VALUE}{AT}host.example/repo.git"], f"user:{VALUE}", "host.example"),
        ([*PEM, "après la clé"], "secretbody", "après la clé"),
        (["BEGIN", *PEM[:2], "fin sans marqueur"], "secretbody", ""),
    ],
)
def test_secret_shapes_are_masked_in_logs(lines: list[str], secret: str, kept: str) -> None:
    filtered = "\n".join(filter_logs(lines))
    assert secret not in filtered
    assert MASK in filtered
    assert kept in filtered


class CallCounter:
    """Remplace `mask_text` : compte les appels et la taille maximale du texte reçu."""

    def __init__(self) -> None:
        self.calls = 0
        self.longest = 0
        self.total = 0

    def __call__(self, text: str) -> str:
        self.calls += 1
        self.total += len(text)
        self.longest = max(self.longest, len(text))
        return text


@pytest.fixture
def counter(monkeypatch: pytest.MonkeyPatch) -> CallCounter:
    counting = CallCounter()
    monkeypatch.setattr(redact_module, "mask_text", counting)
    return counting


def test_structured_values_are_masked_whatever_their_shape() -> None:
    token_a, token_b = "gh" + "p_" + "a1" * 15, "gh" + "p_" + "b2" * 15
    masked = redact_value({token_a: 1, token_b: 2}, frozenset())
    assert isinstance(masked, dict) and sorted(masked.values()) == [1, 2]  # aucune perte
    assert token_a not in repr(masked) and token_b not in repr(masked)
    assert redact_value({"mot_de_passe": "ordinaire"}, frozenset({"mot_de_passe"})) == {
        "mot_de_passe": MASK
    }
    assert redact_value({"liste": ("a", "b")}, frozenset()) == {"liste": ["a", "b"]}


@pytest.mark.parametrize(
    "value",
    [
        {"cles": [PEM[0], 1, f"corps {VALUE}", PEM[2]]},  # liste mixte
        {"a": PEM[0], "b": f"corps {VALUE}", "c": PEM[2]},  # champs successifs d'un dict
        {"x": [[PEM[0]], [f"corps {VALUE}"], [PEM[2]]]},  # listes imbriquées
    ],
)
def test_one_private_key_split_across_fields_is_masked_whole(value: Any) -> None:
    assert VALUE not in repr(redact_value(value, frozenset()))


def test_ordinary_text_is_not_overmasked() -> None:
    plain = [
        "ssh -p2222 host.example",
        "docker run -p8080:80 image",
        "https://gitlab.example.org/x?assignee=bob@example.org",
        "npm i https://registry.example/@scope/pkg",
        "global-platform-team",
        "glance-dashboard-v2",
        "sk-payments-service-2024",
        "https://gitlab.example.org/foreman-demo/global-platform-team/glance-dashboard-v2",
    ]
    assert [mask_text(line) for line in plain] == plain
    assert filter_logs(plain) == plain
    assert redact_value({"web_url": plain[-1], "path": plain[4]}, frozenset()) == {
        "web_url": plain[-1],
        "path": plain[4],
    }
    # Deux blocs sur une ligne : seul ce qui est entre BEGIN et END est masqué.
    assert "milieu" in mask_text(f"{PEM[0]} a {PEM[2]} milieu {PEM[0]} b {PEM[2]}")


def test_a_flood_of_log_lines_is_counted_not_processed(counter: CallCounter) -> None:
    filtered = filter_logs(["eyJ-" * 500] * 10_000)
    assert counter.calls <= 60  # les lignes qui ne tiennent plus ne sont pas masquées
    counter.calls = 0
    filter_logs(["x"] * 100_000)
    assert counter.calls <= 60  # au plus 50 lignes conservées
    assert filtered[-1].startswith("… ") and "ligne(s) omise(s)" in filtered[-1]


def test_the_omission_line_counts_in_the_four_kib() -> None:
    lines = ["a" * 409] * 9 + [
        "b" * 400,
        "c" * 10,
    ]  # 4091 octets tiennent, avec la ligne d'omission non
    filtered = filter_logs(lines)
    assert sum(len(line.encode()) + 1 for line in filtered) <= 4096


def test_work_is_bounded_by_keys_nodes_and_lines(counter: CallCounter) -> None:
    long_keys = {f"k{i}" + "x" * 2000: "v" for i in range(10_000)}
    masked = redact_value(long_keys, frozenset())
    assert isinstance(masked, dict) and masked["truncated"] is True
    assert counter.longest <= 500 and counter.total <= 32 * 1024 + 500  # caractères masqués
    counter.calls = 0
    redact_value({f"k{i}": "v" for i in range(5_000)}, frozenset())
    assert counter.calls <= 1_000  # nombre de clés traitées
    counter.calls = 0
    redact_value({"a": ["x"] * 5_000}, frozenset())
    assert counter.calls <= 1_000  # nombre d'éléments traités
    counter.calls = 0
    redact_value("ligne\n" * 10_000, frozenset())
    assert counter.calls <= 100  # nombre de lignes d'une chaîne


async def test_a_non_json_output_is_normalised_before_masking_and_keeps_the_resource() -> None:
    leaky = {"group_id": 2000, "extra": (f"{AUTH}: {BEARER} {VALUE}",), "meta": {1: "x"}}
    world = make_world(gitlab=MalformedAdapter(leaky, []))
    started = await start(world, ONE_GROUP)
    result = await world.gateway.call(call_for(started))
    assert VALUE not in repr(result.output) + repr(result.audit)
    assert result.output["meta"] == {"1": "x"}  # clé entière : texte, sans erreur après l'effet
    assert [r.external_id for r in result.resources] == ["2000"]


# --- 6b. Le temps de chaque motif croît linéairement ------------------------------------------

UNITS = {
    "mot": "token",
    "mots": "pass",
    "lettres": "A",
    "jwt": "eyJ-",
    "cle": "-----BEGIN PRIVATE KEY-----",
    "url": "http://",
    "url-arobase": "http://a@",
    "basic": "Basic ",
    "entete": "Authorization ",
    "nom": "a_",
    "option": "-password ",
    "egal": "token=",
    "guillemet": 'password="',
    "blancs": " ",
    "jetons": "token a ",
    "curl": "cur" + "l -u a ",
    "login": "docker login ",
    "mysql": "mysql x ",
}
SMALL, LARGE, GROWTH_MAX, DEADLINE_S = 20_000, 80_000, 9.0, 2.0


@contextlib.contextmanager
def deadline(seconds: float) -> Any:
    """Interrompt un traitement qui s'emballe (une régression exponentielle ne bloque pas la CI)."""

    def stop(signum: int, frame: Any) -> None:
        raise AssertionError("traitement trop long")

    previous = signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Apply:
    def __init__(self, pattern: Any) -> None:
        self._pattern = pattern

    def __call__(self, text: str) -> None:
        self._pattern.sub(MASK, text)


def best_time(action: Any, text: str) -> float:
    best = float("inf")
    for _ in range(5):
        started = time.perf_counter()
        with deadline(DEADLINE_S):
            action(text)
        best = min(best, time.perf_counter() - started)
    return best


@pytest.mark.parametrize("name", sorted(UNITS))
def test_masking_time_grows_linearly_with_the_input(name: str) -> None:
    unit = UNITS[name]
    small, large = unit * (SMALL // len(unit)), unit * (LARGE // len(unit))
    for pattern in ALL_PATTERNS:
        apply = Apply(pattern)
        ratio = best_time(apply, large) / max(best_time(apply, small), 2e-4)
        assert ratio < GROWTH_MAX, (pattern.pattern[:60], ratio)
    with deadline(DEADLINE_S * 4):  # filet absolu : tout le chemin public sur 100 Ko
        mask_text(large)
        filter_logs([large] * 200)
        redact_value({"a": large, "b": [large] * 2_000}, frozenset())


# --- 7. Matrice minimale ----------------------------------------------------------------------


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
