"""S11 de bout en bout (critère de fin de #42) : la même demande rejouée ne crée rien en double.

En processus et en mémoire, modèle rejoué (`s01.yaml`), faux adaptateurs. La variante PostgreSQL
avec redémarrage est dans `tests/db/test_s11_restart.py`.
"""

import json
from pathlib import Path

import pytest
from s01_run import normalize
from s11_run import run_s11

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/src/features/cards/s11-events.json"


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


async def test_s11_same_request_replayed_creates_nothing_twice() -> None:
    run = await run_s11()
    project_id, state = run.project_id, run.state

    # 1-2. Autre plan, autre hash (D1 : base = registre rempli) ; 2e `succeeded`.
    assert run.second.plan.plan_hash != run.first.plan.plan_hash
    assert run.second.plan.plan_id != run.first.plan.plan_id
    executions = [
        e.data for e in run.second.events if e.type == "card" and e.data.kind == "execution"
    ]
    final = executions[-1]
    assert final.state == "succeeded"

    # 3. Registre et faux inchangés : mêmes 6 external_id, aucune ligne en plus.
    ids = sorted((r.provider, r.resource_type, r.external_id) for r in run.registry_after_first)
    assert len(ids) == 6
    assert ids == sorted(
        (r.provider, r.resource_type, r.external_id) for r in run.registry_after_second
    )
    before, after = dict(run.fakes_after_first), dict(run.fakes_after_second)
    # Écart au plan : les deux playbooks (étapes 7-8) sont rappelés (clé propre à l'exécution) ; le
    # faux répond « ok » sans rien changer. Aucune ressource n'est créée : seuls `runs` avance.
    assert len(after.pop("runs")) == len(before.pop("runs")) + 2
    assert after == before

    # 3 bis. Audit : `replayed` seulement à l'étape 1 de la 2e exécution, `executed`+reused ensuite.
    audit = await state.stores.audit.list_for_project(project_id)
    second_execution = final.execution_id
    mine = [a for a in audit if a.execution_id == second_execution and a.step_seq is not None]
    by_step = {a.step_seq: a for a in mine if a.decision in ("replayed", "executed")}
    assert by_step[1].decision == "replayed"
    for seq in range(2, 7):
        assert by_step[seq].decision == "executed", seq
        assert (by_step[seq].result_redacted or {}).get("reused") is True, seq

    # 4. Carte 2 : 8/8 étapes, 6 ressources réutilisées ; seq contigus ; aucun secret.
    assert [s.status for s in final.steps] == ["succeeded"] * 8
    assert len(final.resources) == 6 and all(r.reused for r in final.resources)
    assert [e.seq for e in run.second.events] == list(range(1, len(run.second.events) + 1))
    dump = json.dumps([e.model_dump(mode="json") for e in run.second.events])
    assert "FOREMAN_" not in dump and "token" not in dump.lower() and "secret" not in dump.lower()


async def test_the_committed_front_fixture_is_up_to_date() -> None:
    run = await run_s11()
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert normalize(run.second.events) == committed, "fixture périmé : lancez `make s11-fixture`"
