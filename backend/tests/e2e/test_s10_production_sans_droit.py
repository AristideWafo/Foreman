"""S10 de bout en bout (critère de fin de #39) : production sans droit, en processus et en mémoire.

Le développeur ne peut pas exécuter en production : sa validation (202) n'écrit aucune exécution,
il ne peut pas appeler `admin-approvals` (403), l'administrateur approuve (201) et l'exécution
réussit au niveau 2, auditée R7 au nom du demandeur. PostgreSQL est couvert par la suite de contrat.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from s01_run import normalize
from s10_run import run_s10

from foreman.core.events import AnyEvent
from foreman.core.identity import member_id

FIXTURE = Path(__file__).resolve().parents[3] / "frontend/src/features/cards/s10-events.json"


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


def cards(events: list[AnyEvent], kind: str) -> list[Any]:
    return [e.data for e in events if e.type == "card" and e.data.kind == kind]


async def test_s10_production_needs_an_admin_and_runs_at_level_2_in_the_requesters_name() -> None:
    run = await run_s10()
    # 1. Carte plan : production, niveau 2, approuvable, admin requis.
    (plan,) = cards(run.after_plan, "plan")
    assert (plan.environment, plan.autonomy_level) == ("production", 2)
    assert (plan.approvable, plan.admin_approval_required) == (True, True)
    assert plan.skills in (None, [])

    # 2. Validation du développeur : 202, aucune exécution, plan validé, approbation pending R7.
    assert (
        run.dev_validation_attempt.status_code == 403
    )  # le développeur ne valide pas : rien d'écrit
    assert run.after_dev_validation_attempt == run.after_plan
    assert run.dev_approval.status_code == 202
    assert run.dev_approval.json()["status"] == "approval_required"
    assert run.executions_after_dev_approval == []
    assert cards(run.after_dev_approval, "execution") == []
    (pending,) = cards(run.after_dev_approval, "approval")
    assert (pending.status, pending.rule_id, pending.requested_by.name) == (
        "pending",
        "R7-ecriture-production",
        "dev",
    )
    assert pending.approver_roles == ["team_admin", "org_admin"]
    record = await run.state.stores.plans.get(run.project_id, run.plan_id)
    assert record is not None and record.status in ("dev_approved", "executed")

    # 3. Le développeur ne peut pas approuver comme admin : 403, rien n'est écrit.
    assert run.dev_admin_attempt.status_code == 403
    assert run.after_dev_attempt == run.after_dev_approval

    # 4. L'administrateur approuve : 201, exécution réussie au niveau 2, audit R7 au nom de dev.
    assert run.admin_approval.status_code == 201
    final = cards(run.events, "execution")[-1]
    assert (final.state, final.autonomy_level) == ("succeeded", 2)
    assert cards(run.events, "approval")[-1].status == "approved"
    assert cards(run.events, "approval")[-1].decided_by.name == "admin"
    audit = await run.state.stores.audit.list_for_project(run.project_id)
    writes = [a for a in audit if a.rule_id == "R7-ecriture-production"]
    allowed = [a for a in writes if a.decision == "allow"]
    assert len(allowed) == 2 and {a.actor for a in writes} == {str(member_id("dev"))}

    # 5. Enveloppes contiguës en seq ; aucun secret.
    assert [e.seq for e in run.events] == list(range(1, len(run.events) + 1))
    dump = json.dumps([e.model_dump(mode="json") for e in run.events])
    assert "FOREMAN_" not in dump and "token" not in dump.lower() and "secret" not in dump.lower()


async def test_the_committed_front_fixture_is_up_to_date() -> None:
    run = await run_s10()
    committed = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert normalize(run.events) == committed, "fixture périmé : lancez `make s10-fixture`"
