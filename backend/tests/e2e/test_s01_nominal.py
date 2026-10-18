"""S1 de bout en bout (critère de fin de #31) : en processus, en mémoire, modèle rejoué, faux.

PostgreSQL est couvert par la suite de contrat commune des dépôts (même code, même contrat).
"""

import json
from pathlib import Path

import pytest
from s01_run import normalize, run_s01

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/src/features/cards/s01-events.json"
EXPECTED_TOOLS = [
    "gitlab.create_group",
    "gitlab.create_group",
    "gitlab.create_group",
    "gitlab.create_project",
    "gitlab.create_project",
    "server.apply_playbook",
    "server.apply_playbook",
    "server.healthcheck",
]


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


async def test_s01_runs_end_to_end_through_the_gateway() -> None:
    state, project_id, events = await run_s01()

    # Ordre du contrat : plan réémis (dev_approved) AVANT la carte d'exécution, qui précède tout
    # execution_step / execution_log ; ceux-ci visent la carte d'EXÉCUTION.
    cards = [(i, e.data) for i, e in enumerate(events) if e.type == "card"]
    plan_proposed = next(i for i, d in cards if d.kind == "plan" and d.status == "proposed")
    plan_approved = next(i for i, d in cards if d.kind == "plan" and d.status == "dev_approved")
    first_execution, execution_card = next((i, d) for i, d in cards if d.kind == "execution")
    assert plan_proposed < plan_approved < first_execution
    assert next(d for i, d in cards if i == plan_approved).approvable is False
    progress = [
        (i, e) for i, e in enumerate(events) if e.type in ("execution_step", "execution_log")
    ]
    assert progress and all(i > first_execution for i, _ in progress)
    assert {e.data.card_id for _, e in progress} == {execution_card.card_id}
    final = cards[-1][1]
    assert final.kind == "execution" and final.state == "succeeded"
    assert [s.status for s in final.steps] == ["succeeded"] * 8
    assert [s.tool for s in final.steps] == EXPECTED_TOOLS

    # État persisté : exécution réussie, plan exécuté, 8 étapes.
    execution_id = execution_card.execution_id
    execution = await state.stores.executions.get(project_id, execution_id)
    assert execution is not None and execution.state == "succeeded"
    assert [s.status for s in execution.steps] == ["succeeded"] * 8
    plan = await state.stores.plans.get(project_id, execution.plan_id)
    assert plan is not None and plan.status == "executed"

    # Registre du projet : 3 groupes, 2 dépôts, 1 projet serveur.
    registry = await state.stores.registry.list_for_project(project_id)
    kinds = sorted((r.provider, r.resource_type) for r in registry)
    assert kinds == [("gitlab", "gitlab_group")] * 3 + [("gitlab", "gitlab_project")] * 2 + [
        ("server", "server_project")
    ]

    # L'audit reconstitue l'exécution : qui, quel outil, quelle décision, quelle règle, quel plan.
    audit = [
        a for a in await state.stores.audit.list_for_project(project_id) if a.decision == "allow"
    ]
    assert [a.tool for a in audit] == EXPECTED_TOOLS
    assert [a.step_seq for a in audit] == list(range(1, 9))
    assert {a.execution_id for a in audit} == {execution_id}
    assert {a.plan_hash for a in audit} == {plan.content_hash}
    assert all(a.actor and a.rule_id for a in audit)
    assert [a.rule_id for a in audit][-1] == "R1-lecture"


async def test_the_committed_front_fixture_is_up_to_date() -> None:
    _, _, events = await run_s01()
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert normalize(events) == committed, "fixture périmé : lancez `make s01-fixture` et committez"
