"""Adaptateurs simulés : idempotence, concurrence, état inspectable, conformité au catalogue."""

import asyncio
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import JsonValue

from foreman.core.ports import AdapterError, ForeignResource, ToolAdapter
from foreman.core.references import resolve_params
from foreman.core.turn import ProposePlanArguments
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.replay_provider import ReplayProvider
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer

ROOT_PARENT = 1000
GROUP: dict[str, JsonValue] = {
    "parent_group_id": ROOT_PARENT,
    "name": "Safe Eat",
    "path": "safe-eat",
}
PLAYBOOK: dict[str, JsonValue] = {
    "environment": "staging",
    "project": "safe-eat",
    "playbook": "bootstrap_project",
    "mode": "apply",
}


def managed(resources: dict[int, Any]) -> dict[int, Any]:
    """Ressources créées par Foreman (le fake sème aussi des ressources étrangères)."""
    return {i: r for i, r in resources.items() if "managed-by=foreman" in r.description}


def as_adapters() -> dict[str, ToolAdapter]:
    """Vérifié par mypy : chaque fake respecte le port."""
    return {"gitlab": SimulatedGitLab(), "server": SimulatedServer(), "dns": SimulatedDns()}


# --- GitLab -------------------------------------------------------------------------------------


async def test_gitlab_replaying_the_same_key_creates_nothing_more() -> None:
    gitlab = SimulatedGitLab()
    first = await gitlab.execute("gitlab.create_group", GROUP, "k1")
    again = await gitlab.execute("gitlab.create_group", GROUP, "k1")
    assert again.output == first.output
    assert len(managed(gitlab.groups)) == 1
    sub: dict[str, JsonValue] = {
        **GROUP,
        "parent_group_id": first.output["group_id"],
        "path": "api",
    }
    project = {**sub, "boilerplate": "go-api"}
    repo1 = await gitlab.execute("gitlab.create_project", project, "k2")
    repo2 = await gitlab.execute("gitlab.create_project", project, "k2")
    assert repo2.output == repo1.output
    assert len(managed(gitlab.projects)) == 1


async def test_gitlab_state_is_inspectable_and_marked_as_managed() -> None:
    gitlab = SimulatedGitLab()
    result = await gitlab.execute("gitlab.create_group", GROUP, "k1")
    group = gitlab.groups[int(str(result.output["group_id"]))]
    assert group.full_path == "foreman-demo/safe-eat"
    assert group.web_url == "https://gitlab.example.org/foreman-demo/safe-eat"
    assert "managed-by=foreman" in group.description
    assert result.output["web_url"] == group.web_url


async def test_gitlab_concurrent_calls_for_the_same_group_create_one() -> None:
    gitlab = SimulatedGitLab()
    results = await asyncio.gather(
        *(gitlab.execute("gitlab.create_group", GROUP, f"k{i}") for i in range(8))
    )
    assert len(managed(gitlab.groups)) == 1
    assert len({str(r.output["group_id"]) for r in results}) == 1


async def test_gitlab_refuses_an_unknown_parent_and_foreign_tools() -> None:
    gitlab = SimulatedGitLab()
    with pytest.raises(AdapterError):
        await gitlab.execute("gitlab.create_group", {**GROUP, "parent_group_id": 424242}, "k")
    with pytest.raises(AdapterError):
        await gitlab.execute("gitlab.create_project", {**GROUP, "boilerplate": "go-api"}, "k")
    with pytest.raises(AdapterError):
        await gitlab.execute("server.apply_playbook", PLAYBOOK, "k")
    with pytest.raises(AdapterError):
        await gitlab.execute("gitlab.create_group", {**GROUP, "parent_group_id": True}, "k")
    assert managed(gitlab.groups) == {}


# --- Serveur ------------------------------------------------------------------------------------


async def test_server_replaying_the_same_key_returns_the_previous_result_without_a_new_run() -> (
    None
):
    server = SimulatedServer()
    first = await server.execute("server.apply_playbook", PLAYBOOK, "exec:1:bootstrap_project")
    again = await server.execute("server.apply_playbook", PLAYBOOK, "exec:1:bootstrap_project")
    assert again == first
    assert first.output["status"] == "changed"
    assert server.runs == ["run-0001"]
    assert server.projects[("staging", "safe-eat")].runs == ["run-0001"]


async def test_server_a_second_apply_under_a_new_key_changes_nothing() -> None:
    server = SimulatedServer()
    await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    second = await server.execute("server.apply_playbook", PLAYBOOK, "k2")
    assert second.output["status"] == "ok"
    assert second.output["changed_tasks"] == []


async def test_server_concurrent_calls_with_the_same_key_run_once() -> None:
    server = SimulatedServer()
    results = await asyncio.gather(
        *(server.execute("server.apply_playbook", PLAYBOOK, "same-key") for _ in range(8))
    )
    assert len(server.runs) == 1
    assert all(r == results[0] for r in results)


async def test_server_check_mode_changes_no_state_and_emits_log_lines() -> None:
    server = SimulatedServer()
    checked = await server.execute(
        "server.apply_playbook", {**PLAYBOOK, "mode": "check"}, "k-check"
    )
    assert server.projects == {} and server.runs == []
    assert checked.logs and checked.logs[0].startswith("PLAY [bootstrap_project]")


async def test_server_deploy_needs_a_bootstrapped_project() -> None:
    server = SimulatedServer()
    deploy = {**PLAYBOOK, "playbook": "deploy_compose"}
    with pytest.raises(AdapterError):
        await server.execute("server.apply_playbook", deploy, "k1")
    await server.execute("server.apply_playbook", PLAYBOOK, "k2")
    result = await server.execute("server.apply_playbook", deploy, "k3")
    assert result.output["status"] == "changed"
    assert server.projects[("staging", "safe-eat")].deployed is True


async def test_server_healthcheck_reflects_the_deployment() -> None:
    server = SimulatedServer()
    params: dict[str, JsonValue] = {"environment": "staging", "project": "safe-eat"}
    before = await server.execute("server.healthcheck", params, "h")
    assert before.output["status"] == "failed"
    await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    await server.execute("server.apply_playbook", {**PLAYBOOK, "playbook": "deploy_compose"}, "k2")
    after = await server.execute("server.healthcheck", params, "h")
    assert after.output == {"status": "ok", "http_status": 200, "database": "ok"}


async def test_server_refuses_unknown_playbooks_and_tools() -> None:
    server = SimulatedServer()
    with pytest.raises(AdapterError):
        await server.execute("server.apply_playbook", {**PLAYBOOK, "playbook": "rm_rf"}, "k")
    with pytest.raises(AdapterError):
        await server.execute("server.exec_adhoc", {"cmd": "id"}, "k")
    assert server.projects == {}


# --- DNS ----------------------------------------------------------------------------------------


async def test_dns_lists_the_wildcard_from_the_referentiel_and_never_writes() -> None:
    catalog = load_catalog(catalog_dir_from_env(), environment="staging")
    dns = SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data)
    before = dns.records
    result = await dns.execute("dns.list_records", {"environment": "staging"}, "k")
    assert result.output == {
        "records": [
            {"name": "*.staging.example.org", "type": "CNAME", "target": "server-staging-1"}
        ]
    }
    with pytest.raises(AdapterError):
        await dns.execute("dns.create_record", {"name": "x"}, "k")
    assert dns.records == before


# --- Cohérence avec le catalogue et le scénario S1 ----------------------------------------------


async def test_the_recorded_s01_plan_runs_on_the_fakes_and_obeys_the_tool_schemas() -> None:
    """Chaque étape enregistrée valide le schéma de son outil et s'exécute sur son fake."""
    catalog = load_catalog(catalog_dir_from_env(), environment="staging")
    reply = await ReplayProvider.s01(catalog_dir_from_env()).complete(["bonjour"])
    plan = ProposePlanArguments.model_validate(reply.tool_calls[0].arguments)
    adapters = as_adapters()
    gitlab = adapters["gitlab"]
    assert isinstance(gitlab, SimulatedGitLab)
    server = adapters["server"]
    assert isinstance(server, SimulatedServer)
    outputs: dict[int, dict[str, JsonValue]] = {}
    for seq, step in enumerate(plan.steps, start=1):
        assert step.tool is not None and step.params is not None
        definition = catalog.tools[step.tool]
        params = resolve_params(
            step.params, outputs, seq
        )  # les `$from` visent des étapes antérieures
        Draft202012Validator(definition.input).validate(params)
        outcome = await adapters[definition.connector].execute(step.tool, params, f"k{seq}")
        assert outcome.logs
        assert all(outcome.output[k] is not None for k in definition.output)
        outputs[seq] = outcome.output
    assert {g.path for g in managed(gitlab.groups).values()} == {"safe-eat", "backend", "frontend"}
    assert {p.path for p in managed(gitlab.projects).values()} == {"safe-eat-api", "safe-eat-web"}
    assert server.projects[("staging", "safe-eat")].deployed is True
    health = await server.execute(
        "server.healthcheck", {"environment": "staging", "project": "safe-eat"}, "h"
    )
    assert health.output["status"] == "ok"


# --- Ressources étrangères : on n'adopte jamais ce que Foreman n'a pas créé ----------------------


async def test_gitlab_never_adopts_a_group_that_foreman_did_not_create() -> None:
    gitlab = SimulatedGitLab()
    legacy_before = dict(gitlab.groups)
    params: dict[str, JsonValue] = {"parent_group_id": ROOT_PARENT, "name": "L", "path": "legacy"}
    with pytest.raises(ForeignResource):
        await gitlab.execute("gitlab.create_group", params, "k1")
    assert gitlab.groups == legacy_before


async def test_gitlab_never_adopts_a_repository_that_foreman_did_not_create() -> None:
    gitlab = SimulatedGitLab()
    params: dict[str, JsonValue] = {
        "parent_group_id": 1500,
        "name": "legacy-api",
        "path": "legacy-api",
        "boilerplate": "go-api",
    }
    projects_before = dict(gitlab.projects)
    with pytest.raises(ForeignResource):
        await gitlab.execute("gitlab.create_project", params, "k1")
    assert gitlab.projects == projects_before


async def test_gitlab_root_group_comes_from_the_referentiel() -> None:
    catalog = load_catalog(catalog_dir_from_env(), environment="staging")
    gitlab = SimulatedGitLab.from_referentiel(catalog.referentiels["gitlab-groups"].data)
    result = await gitlab.execute("gitlab.create_group", GROUP, "k1")
    assert result.output["web_url"] == "https://gitlab.example.org/foreman-demo/safe-eat"
    other = SimulatedGitLab(root_group_id=77, root_group_path="autre")
    with pytest.raises(AdapterError):
        await other.execute("gitlab.create_group", GROUP, "k1")  # 1000 n'est plus la racine


# --- Serveur : isolation du cache, run_id, clés d'état ---------------------------------------


async def test_server_cached_results_cannot_be_altered_by_the_caller() -> None:
    server = SimulatedServer()
    first = await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    first.output["status"] = "pirate"
    first.logs.append("pirate")
    again = await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    assert again.output["status"] == "changed"
    assert "pirate" not in again.logs
    again.output["changed_tasks"].append("pirate")  # type: ignore[union-attr]
    third = await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    assert "pirate" not in third.output["changed_tasks"]  # type: ignore[operator]


async def test_server_run_ids_never_collide_between_check_and_apply() -> None:
    server = SimulatedServer()
    checked = await server.execute("server.apply_playbook", {**PLAYBOOK, "mode": "check"}, "k1")
    applied = await server.execute("server.apply_playbook", PLAYBOOK, "k2")
    again = await server.execute("server.apply_playbook", {**PLAYBOOK, "mode": "check"}, "k3")
    run_ids = {checked.output["run_id"], applied.output["run_id"], again.output["run_id"]}
    assert len(run_ids) == 3
    assert server.runs == [applied.output["run_id"]]


async def test_server_state_is_keyed_by_environment_and_project() -> None:
    server = SimulatedServer()
    await server.execute("server.apply_playbook", PLAYBOOK, "k1")
    await server.execute("server.apply_playbook", {**PLAYBOOK, "playbook": "deploy_compose"}, "k0")
    other = {**PLAYBOOK, "environment": "production"}
    with pytest.raises(AdapterError):
        await server.execute("server.apply_playbook", {**other, "playbook": "deploy_compose"}, "k2")
    assert set(server.projects) == {("staging", "safe-eat")}
    health = await server.execute(
        "server.healthcheck", {"environment": "production", "project": "safe-eat"}, "h"
    )
    assert health.output["status"] == "failed"
    staging = await server.execute(
        "server.healthcheck", {"environment": "staging", "project": "safe-eat"}, "h"
    )
    assert staging.output["status"] == "ok"
