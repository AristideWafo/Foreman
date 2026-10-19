"""S12 de bout en bout (critère de fin de #44) : un plan dont la base a changé n'est pas approuvé.

En mémoire, modèle rejoué, horloge injectée, faux adaptateurs.
"""

import json
from pathlib import Path

import pytest
from s01_run import normalize
from s12_run import run_catalog_changed, run_expired, run_project_changed

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/src/features/cards/s12-events.json"
SECRET_WORDS = ("FOREMAN_", "token", "secret")


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


def cards(events: list, kind: str, plan_id) -> list:  # type: ignore[type-arg]
    return [
        e.data
        for e in events
        if e.type == "card" and e.data.kind == kind and e.data.plan_id == plan_id
    ]


def assert_invariants(events: list) -> None:  # type: ignore[type-arg]
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
    dump = json.dumps([e.model_dump(mode="json") for e in events]).lower()
    assert not any(word.lower() in dump for word in SECRET_WORDS)


async def test_s12_project_changed_invalidates_the_older_plan() -> None:
    run = await run_project_changed()
    assert run.v2_response.status_code == 201 and run.v3_response.status_code == 201
    assert run.v1_response.status_code == 409
    assert run.v1_response.json()["error"] == "plan_not_approvable"

    # Carte v1 : invalidée, pour cause de projet modifié (le registre).
    invalidated = cards(run.events, "plan", run.v1.plan_id)[-1]
    assert invalidated.status == "invalidated"
    assert invalidated.invalidation.reason == "project_changed"
    assert any(c.kind == "registry" for c in invalidated.invalidation.changes)

    # Aucune exécution pour v1 : seules v2 et v3 en ont une ; une seule audit `invalidated`.
    executions = {
        e.data.execution_id for e in run.events if e.type == "card" and e.data.kind == "execution"
    }
    assert len(executions) == 2
    audit = await run.state.stores.audit.list_for_project(run.project_id)
    assert [a.decision for a in audit if a.plan_id == run.v1.plan_id].count("invalidated") == 1

    # v3 : base à jour, exécution réussie avec des ressources réutilisées.
    final = [e.data for e in run.events if e.type == "card" and e.data.kind == "execution"][-1]
    assert final.state == "succeeded"
    assert len(final.resources) == 6 and all(r.reused for r in final.resources)
    rows = await run.state.stores.registry.list_for_project(run.project_id)
    keys = [(r.provider, r.resource_type, r.external_id) for r in rows]
    assert len(keys) == len(set(keys)) == 6
    assert_invariants(run.events)


async def test_s12_catalog_changed_blocks_the_admin_approval(tmp_path: Path) -> None:
    run = await run_catalog_changed(tmp_path)
    assert run.dev_response.status_code == 202
    assert run.admin_response.status_code == 409
    assert run.admin_response.json()["error"] == "plan_not_approvable"
    plan = cards(run.events, "plan", run.plan.plan_id)[-1]
    assert plan.status == "invalidated" and plan.invalidation.reason == "catalog_changed"
    assert [(c.kind, c.name) for c in plan.invalidation.changes] == [
        ("referential", "infra-staging")
    ]
    assert cards(run.events, "approval", run.plan.plan_id)[-1].status == "invalidated"
    assert not [e for e in run.events if e.type == "card" and e.data.kind == "execution"]
    assert_invariants(run.events)


async def test_s12_expired_plan_is_closed_once() -> None:
    run = await run_expired()
    assert [p.id for p in run.swept] == [run.plan.plan_id] and run.status == "expired"
    assert run.response.status_code == 409
    plan_cards = cards(run.events, "plan", run.plan.plan_id)
    assert [c.status for c in plan_cards].count("expired") == 1
    assert not [e for e in run.events if e.type == "card" and e.data.kind == "execution"]
    assert_invariants(run.events)


async def test_the_committed_front_fixture_is_up_to_date() -> None:
    run = await run_project_changed()
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert normalize(run.events) == committed, "fixture périmé : lancez `make s12-fixture`"
