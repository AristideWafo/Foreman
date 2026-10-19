"""S2 de bout en bout (critère de fin de #34) : en processus, en mémoire, modèle rejoué, faux.

Environnement non précisé : carte de clarification, aucun plan, puis la réponse `staging` (route)
relance un tour qui propose le plan. PostgreSQL est couvert par la suite de contrat des dépôts.
"""

import json
from pathlib import Path

import pytest
from s01_run import normalize
from s02_run import run_s02

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/src/features/cards/s02-events.json"


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


async def test_s02_asks_for_the_environment_then_plans_for_the_answer() -> None:
    run = await run_s02()

    # Tour 1 : carte de clarification (options du serveur), question persistée, aucun plan.
    ask_cards = [e.data for e in run.after_ask if e.type == "card"]
    assert [c.kind for c in ask_cards] == ["clarification"]
    assert [(q.field, q.options, q.status) for q in ask_cards[0].questions] == [  # type: ignore[union-attr]
        ("environment", ["staging", "production"], "open")
    ]
    assert [(q.id, q.status) for q in run.questions_after_ask] == [("q1-1", "open")]

    # La route a accepté la réponse (202), la question est répondue, le plan vise staging.
    assert run.answer_status == 202
    questions = await run.state.projects.get_open_questions(run.project_id)
    assert [(q.id, q.status, q.answer) for q in questions] == [("q1-1", "answered", "staging")]
    plan_cards = [e.data for e in run.events if e.type == "card" and e.data.kind == "plan"]
    assert len(plan_cards) == 1 and plan_cards[0].environment == "staging"  # type: ignore[union-attr]
    # Le plan n'existe qu'après la réponse : c'est la première (et seule) version du projet.
    record = await run.state.stores.plans.get(run.project_id, plan_cards[0].plan_id)  # type: ignore[union-attr, arg-type]
    assert record is not None and record.version == 1 and record.status == "proposed"
    assert record.content["environment"] == "staging"
    assert all(e.data.kind != "plan" for e in run.after_ask if e.type == "card")

    # Enveloppes contiguës en seq ; aucune clef secrète ni écho de saisie dans le flux.
    assert [e.seq for e in run.events] == list(range(1, len(run.events) + 1))
    dump = json.dumps([e.model_dump(mode="json") for e in run.events])
    assert "FOREMAN_" not in dump and "token" not in dump.lower() and "secret" not in dump.lower()


async def test_the_committed_front_fixture_is_up_to_date() -> None:
    run = await run_s02()
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert normalize(run.events) == committed, "fixture périmé : lancez `make s02-fixture`"
