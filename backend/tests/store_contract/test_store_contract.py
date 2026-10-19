"""Contrat des dépôts du moteur : la même suite tourne sur la mémoire et sur PostgreSQL."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from harness import APPROVER, Harness

from foreman.core.events import ClarificationQuestion, EventData, MessageData
from foreman.core.ports import CapacityExceeded
from foreman.core.store import (
    MAX_AUDIT_DURATION_MS,
    ApprovalRefused,
    Approved,
    AuditEntry,
    CompletedReservation,
    DuplicateResource,
    InvalidTransition,
    Lease,
    NewPlan,
    NewReservation,
    NewResource,
    OrphanReservation,
    PlanRecord,
    StaleLease,
    StoreError,
    UnknownProject,
)

FUTURE = datetime(2100, 1, 1, tzinfo=UTC)
PAST = datetime(2000, 1, 1, tzinfo=UTC)
TOO_LONG = MAX_AUDIT_DURATION_MS + 1  # refusé par la table comme par le banc mémoire


async def new_project(h: Harness) -> UUID:
    return (await h.projects.create("p")).id


async def new_plan(
    h: Harness,
    project_id: UUID,
    *,
    keys: tuple[str, ...] | None = None,
    expires_at: datetime = FUTURE,
    plan_hash: str | None = None,
) -> PlanRecord:
    keys = keys or (f"k1-{uuid4().hex}", f"k2-{uuid4().hex}", f"k3-{uuid4().hex}")
    steps = [
        {"seq": i, "tool": "gitlab.create_group", "params": {"name": key}, "idempotency_key": key}
        for i, key in enumerate(keys, start=1)
    ]
    return await h.stores.plans.create(
        NewPlan(
            project_id=project_id,
            content={"environment": "staging", "steps": steps},
            content_hash=plan_hash or "sha256:" + uuid4().hex.ljust(64, "0"),
            skills_used=[],
            expires_at=expires_at,
            requested_by=APPROVER,
        )
    )


async def approve(h: Harness, plan: PlanRecord) -> Approved:
    result = await h.stores.plans.approve(plan.project_id, plan.id, plan.content_hash, APPROVER, 2)
    assert isinstance(result, Approved)
    return result


async def running_execution(h: Harness, project_id: UUID, owner: str = "w1") -> tuple[UUID, Lease]:
    plan = await new_plan(h, project_id)
    execution_id = (await approve(h, plan)).execution_id
    lease = await h.stores.executions.claim_lease(execution_id, owner)
    assert lease is not None
    return execution_id, lease


def audit(project_id: UUID, **overrides: object) -> AuditEntry:
    fields: dict[str, object] = {
        "actor_kind": "engine",
        "project_id": project_id,
        "decision": "allow",
    }
    return AuditEntry(**(fields | overrides))  # type: ignore[arg-type]


# --- Plans et approbation ---------------------------------------------------------------------


async def test_plan_versions_increase_per_project_and_reads_are_scoped(harness: Harness) -> None:
    a, b = await new_project(harness), await new_project(harness)
    first, second = await new_plan(harness, a), await new_plan(harness, a)
    other = await new_plan(harness, b)
    assert (first.version, second.version, other.version) == (1, 2, 1)
    assert (await harness.stores.plans.get(a, first.id)) == first
    assert await harness.stores.plans.get(b, first.id) is None  # autre projet = absent
    with pytest.raises(UnknownProject):  # même refus en mémoire et en PostgreSQL
        await new_plan(harness, uuid4())


async def test_approval_creates_the_execution_with_pending_steps(harness: Harness) -> None:
    project = await new_project(harness)
    plan = await new_plan(harness, project)
    approved = await approve(harness, plan)
    assert approved.created
    stored = await harness.stores.plans.get(project, plan.id)
    assert stored is not None and stored.status == "dev_approved"
    execution = await harness.stores.executions.get(project, approved.execution_id)
    assert execution is not None
    assert execution.state == "running"
    assert [(s.seq, s.status) for s in execution.steps] == [
        (1, "pending"),
        (2, "pending"),
        (3, "pending"),
    ]


async def test_approval_is_idempotent_and_other_outcomes_are_typed_refusals(
    harness: Harness,
) -> None:
    project, other_project = await new_project(harness), await new_project(harness)
    plan = await new_plan(harness, project)
    first = await approve(harness, plan)
    replay = await harness.stores.plans.approve(project, plan.id, plan.content_hash, APPROVER, 2)
    assert replay == Approved(first.approval_id, first.execution_id, created=False)

    wrong_hash = "sha256:" + "f" * 64
    refusals = {
        "plan_hash_mismatch": await harness.stores.plans.approve(
            project, plan.id, wrong_hash, APPROVER, 2
        ),
        "not_found": await harness.stores.plans.approve(
            other_project, plan.id, plan.content_hash, APPROVER, 2
        ),
    }
    for reason, result in refusals.items():
        assert result == ApprovalRefused(reason), reason  # type: ignore[arg-type]
    unknown = await harness.stores.plans.approve(project, uuid4(), plan.content_hash, APPROVER, 2)
    assert unknown == ApprovalRefused("not_found")

    expired = await new_plan(harness, other_project, expires_at=PAST)
    result = await harness.stores.plans.approve(
        other_project, expired.id, expired.content_hash, APPROVER, 2
    )
    assert result == ApprovalRefused("plan_not_approvable")


async def test_an_executed_plan_cannot_be_approved_again(harness: Harness) -> None:
    project = await new_project(harness)
    plan = await new_plan(harness, project, keys=("only",))
    approved = await approve(harness, plan)
    lease = await harness.stores.executions.claim_lease(approved.execution_id, "w1")
    assert lease is not None
    assert isinstance(await harness.stores.executions.reserve_idempotency(lease, 1), NewReservation)
    await harness.stores.executions.complete_step(lease, 1, {"ok": True}, [], [])
    await harness.stores.executions.finish(lease, "succeeded")
    stored = await harness.stores.plans.get(project, plan.id)
    assert stored is not None and stored.status == "executed"
    again = await harness.stores.plans.approve(project, plan.id, plan.content_hash, APPROVER, 2)
    assert again == ApprovalRefused("plan_not_approvable")


async def test_concurrent_approvals_create_a_single_execution(harness: Harness) -> None:
    project = await new_project(harness)
    plan = await new_plan(harness, project)
    results = await asyncio.gather(
        *(
            harness.stores.plans.approve(project, plan.id, plan.content_hash, APPROVER, 2)
            for _ in range(8)
        )
    )
    approved = [r for r in results if isinstance(r, Approved)]
    assert len(approved) == 8  # aucune n'échoue : les rejeux rendent les mêmes identifiants
    assert sum(r.created for r in approved) == 1
    assert len({(r.approval_id, r.execution_id) for r in approved}) == 1


async def test_a_second_plan_waits_while_an_execution_is_active(harness: Harness) -> None:
    project = await new_project(harness)
    first, second = await new_plan(harness, project), await new_plan(harness, project)
    running = await approve(harness, first)
    refused = await harness.stores.plans.approve(
        project, second.id, second.content_hash, APPROVER, 2
    )
    assert refused == ApprovalRefused("execution_in_progress")
    still = await harness.stores.plans.get(project, second.id)
    assert still is not None and still.status == "proposed"  # rien n'a été écrit

    lease = await harness.stores.executions.claim_lease(running.execution_id, "w1")
    assert lease is not None
    await harness.stores.executions.finish(lease, "blocked")
    assert isinstance(await approve(harness, second), Approved)


# --- Bail -------------------------------------------------------------------------------------


async def test_a_lease_is_taken_only_after_expiry_and_the_old_holder_is_fenced(
    harness: Harness,
) -> None:
    project = await new_project(harness)
    execution_id, lease_a = await running_execution(harness, project, "worker-a")
    store = harness.stores.executions
    assert await store.claim_lease(execution_id, "worker-b") is None  # bail valide : refusé
    assert await store.renew(lease_a)

    await harness.expire_lease(lease_a)
    lease_b = await store.claim_lease(execution_id, "worker-b")
    assert lease_b is not None and lease_b.epoch > lease_a.epoch

    # Le worker périmé ne peut plus rien écrire ni renouveler.
    assert not await store.renew(lease_a)
    with pytest.raises(StaleLease):
        await store.reserve_idempotency(lease_a, 1)
    with pytest.raises(StaleLease):
        await store.complete_step(lease_a, 1, {}, [], [])
    with pytest.raises(StaleLease):
        await store.finish(lease_a, "blocked")
    assert await store.renew(lease_b)


async def test_an_expired_lease_cannot_be_renewed_but_can_be_reclaimed(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    await harness.expire_lease(lease)
    assert not await harness.stores.executions.renew(lease)  # personne ne l'a reprise : refusé
    again = await harness.stores.executions.claim_lease(execution_id, "w1")
    assert again is not None and await harness.stores.executions.renew(again)


async def test_the_holder_can_reclaim_its_own_lease_with_a_new_token(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    again = await harness.stores.executions.claim_lease(execution_id, "w1")
    assert again is not None and again.epoch > lease.epoch
    with pytest.raises(StaleLease):
        await harness.stores.executions.finish(lease, "blocked")


async def test_concurrent_claims_of_one_execution_give_a_single_lease(harness: Harness) -> None:
    project = await new_project(harness)
    plan = await new_plan(harness, project)
    execution_id = (await approve(harness, plan)).execution_id
    claims = await asyncio.gather(
        *(harness.stores.executions.claim_lease(execution_id, f"worker-{i}") for i in range(6))
    )
    assert len([c for c in claims if c is not None]) == 1


# --- Idempotence ------------------------------------------------------------------------------


async def test_a_second_reservation_returns_the_previous_result_without_duplicate(
    harness: Harness,
) -> None:
    project, other_project = await new_project(harness), await new_project(harness)
    store = harness.stores.executions
    key = f"create_group:{uuid4().hex}"

    plan = await new_plan(harness, project, keys=(key,))
    lease = await store.claim_lease((await approve(harness, plan)).execution_id, "w1")
    assert lease is not None
    assert isinstance(await store.reserve_idempotency(lease, 1), NewReservation)
    await store.complete_step(
        lease, 1, {"id": "g1"}, [NewResource("gitlab", "group", f"g-{key}")], [audit(project)]
    )
    await store.finish(lease, "succeeded")

    replan = await new_plan(harness, project, keys=(key,))  # même clé, autre exécution
    relane = await store.claim_lease((await approve(harness, replan)).execution_id, "w1")
    assert relane is not None
    assert await store.reserve_idempotency(relane, 1) == CompletedReservation({"id": "g1"})
    assert len(await harness.stores.registry.list_for_project(project)) == 1  # pas de doublon

    # La clé est portée par le projet : un autre projet réserve la sienne sans collision.
    foreign = await new_plan(harness, other_project, keys=(key,))
    foreign_lease = await store.claim_lease((await approve(harness, foreign)).execution_id, "w2")
    assert foreign_lease is not None
    assert isinstance(await store.reserve_idempotency(foreign_lease, 1), NewReservation)


async def test_a_reservation_without_result_is_reported_and_never_replayed_blindly(
    harness: Harness,
) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    assert isinstance(await store.reserve_idempotency(lease, 1), NewReservation)
    # Panne du worker puis reprise par un autre : la réservation existe sans résultat.
    await harness.expire_lease(lease)
    taker = await store.claim_lease(execution_id, "w2")
    assert taker is not None
    assert isinstance(await store.reserve_idempotency(taker, 1), OrphanReservation)


# --- complete_step ----------------------------------------------------------------------------


async def test_complete_step_records_step_resources_and_audit_together(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    assert isinstance(await store.reserve_idempotency(lease, 1), NewReservation)
    resource = NewResource("gitlab", "group", f"g-{uuid4().hex}", "https://gitlab.example/g")
    await store.complete_step(
        lease, 1, {"id": "g1"}, [resource], [audit(project, tool="gitlab.create_group", step_seq=1)]
    )
    assert await harness.stores.registry.contains(project, "gitlab", "group", resource.external_id)
    stranger = await new_project(harness)  # le registre est cloisonné par projet
    assert not await harness.stores.registry.contains(
        stranger, "gitlab", "group", resource.external_id
    )
    other = harness.stores.registry  # une ressource n'a qu'un maître : les autres projets la voient
    assert await other.exists_elsewhere(stranger, "gitlab", "group", resource.external_id)
    assert not await other.exists_elsewhere(project, "gitlab", "group", resource.external_id)
    listed = await harness.stores.registry.list_for_project(project)
    assert [(r.external_id, r.origin, r.execution_id) for r in listed] == [
        (resource.external_id, "created", execution_id)
    ]
    logged = await harness.stores.audit.list_for_project(project)
    assert [(e.tool, e.step_seq) for e in logged] == [("gitlab.create_group", 1)]
    nxt = await store.next_step(execution_id)
    assert nxt is not None and nxt.seq == 2


async def test_when_the_audit_fails_no_resource_is_registered(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    assert isinstance(await store.reserve_idempotency(lease, 1), NewReservation)
    resource = NewResource("gitlab", "group", f"g-{uuid4().hex}")
    with pytest.raises(StoreError):
        await store.complete_step(
            lease,
            1,
            {"id": "g1"},
            [resource],
            [audit(project), audit(project, duration_ms=TOO_LONG)],
        )
    assert not await harness.stores.registry.contains(
        project, "gitlab", "group", resource.external_id
    )
    assert await harness.stores.audit.list_for_project(project) == []
    step = await store.next_step(execution_id)
    assert step is not None and (step.seq, step.status, step.result) == (1, "running", None)
    # La clé reste « réservée sans résultat » : rien n'a été marqué terminé.
    await harness.expire_lease(lease)
    taker = await store.claim_lease(execution_id, "w2")
    assert taker is not None
    assert isinstance(await store.reserve_idempotency(taker, 1), OrphanReservation)


async def test_a_resource_already_registered_rolls_the_whole_step_back(harness: Harness) -> None:
    owner, intruder = await new_project(harness), await new_project(harness)
    external_id = f"g-{uuid4().hex}"
    store = harness.stores.executions
    _, lease_a = await running_execution(harness, owner)
    await store.reserve_idempotency(lease_a, 1)
    await store.complete_step(lease_a, 1, {}, [NewResource("gitlab", "group", external_id)], [])

    execution_b, lease_b = await running_execution(harness, intruder)
    await store.reserve_idempotency(lease_b, 1)
    with pytest.raises(DuplicateResource):
        await store.complete_step(
            lease_b, 1, {}, [NewResource("gitlab", "group", external_id)], [audit(intruder)]
        )
    assert await harness.stores.registry.list_for_project(intruder) == []
    assert await harness.stores.audit.list_for_project(intruder) == []
    step = await store.next_step(execution_b)
    assert step is not None and step.status == "running"


async def test_a_step_cannot_write_the_audit_of_another_project(harness: Harness) -> None:
    project, other = await new_project(harness), await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    assert isinstance(await store.reserve_idempotency(lease, 1), NewReservation)
    resource = NewResource("gitlab", "group", f"g-{uuid4().hex}")
    with pytest.raises(StoreError):
        await store.complete_step(
            lease, 1, {"id": "g1"}, [resource], [audit(project), audit(other)]
        )
    assert await harness.stores.audit.list_for_project(project) == []
    assert await harness.stores.audit.list_for_project(other) == []
    assert not await harness.stores.registry.contains(
        project, "gitlab", "group", resource.external_id
    )
    step = await store.next_step(execution_id)
    assert step is not None and (step.seq, step.status) == (1, "running")  # rien d'écrit


async def test_an_execution_cannot_succeed_while_a_step_is_not_succeeded(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    await store.reserve_idempotency(lease, 1)
    await store.complete_step(lease, 1, {}, [], [])  # les étapes 2 et 3 restent `pending`
    with pytest.raises(InvalidTransition):
        await store.finish(lease, "succeeded")
    execution = await store.get(project, execution_id)
    assert execution is not None and execution.state == "running"
    plan = await harness.stores.plans.get(project, execution.plan_id)
    assert plan is not None and plan.status == "dev_approved"  # le plan n'est pas « executed »
    await store.finish(lease, "blocked")  # l'échec reste possible


async def test_transitions_from_unexpected_states_are_refused(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    with pytest.raises(InvalidTransition):  # étape jamais réservée
        await store.complete_step(lease, 1, {}, [], [])
    with pytest.raises(InvalidTransition):  # étape inexistante
        await store.reserve_idempotency(lease, 99)
    await store.finish(lease, "blocked")
    with pytest.raises(InvalidTransition):  # exécution terminée
        await store.finish(lease, "succeeded")
    with pytest.raises(InvalidTransition):
        await store.reserve_idempotency(lease, 1)
    execution = await store.get(project, execution_id)
    assert execution is not None and execution.state == "blocked"


async def test_next_step_is_the_first_step_not_yet_succeeded(harness: Harness) -> None:
    project = await new_project(harness)
    execution_id, lease = await running_execution(harness, project)
    store = harness.stores.executions
    for seq in (1, 2, 3):
        step = await store.next_step(execution_id)
        assert step is not None and step.seq == seq
        await store.reserve_idempotency(lease, seq)
        await store.complete_step(lease, seq, {"seq": seq}, [], [])
    assert await store.next_step(execution_id) is None


# --- Cloisonnement, registre, audit -----------------------------------------------------------


async def test_an_execution_of_another_project_is_absent(harness: Harness) -> None:
    project, other = await new_project(harness), await new_project(harness)
    execution_id, _ = await running_execution(harness, project)
    assert await harness.stores.executions.get(other, execution_id) is None
    assert await harness.stores.executions.get(project, execution_id) is not None


async def test_registry_and_audit_are_scoped_by_project(harness: Harness) -> None:
    a, b = await new_project(harness), await new_project(harness)
    await harness.stores.audit.append(audit(a, tool="x"))
    await harness.stores.audit.append(audit(b, tool="y"))
    assert [e.tool for e in await harness.stores.audit.list_for_project(a)] == ["x"]
    assert await harness.stores.registry.list_for_project(b) == []
    assert not await harness.stores.registry.contains(a, "gitlab", "group", "absent")


async def test_the_audit_log_refuses_an_invalid_entry_and_writes_nothing(harness: Harness) -> None:
    project = await new_project(harness)
    with pytest.raises(StoreError):
        await harness.stores.audit.append(audit(project, duration_ms=TOO_LONG))
    assert await harness.stores.audit.list_for_project(project) == []


# --- Bornes -----------------------------------------------------------------------------------


async def test_the_project_cap_holds_under_concurrent_creation(harness: Harness) -> None:
    projects = harness.bounded_projects(3)
    results = await asyncio.gather(
        *(projects.create(f"p{i}") for i in range(10)), return_exceptions=True
    )
    created = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, CapacityExceeded)]
    assert (len(created), len(refused)) == (3, 7)  # aucune autre erreur, aucun dépassement


async def test_projects_are_listed_newest_first(harness: Harness) -> None:
    first = await harness.projects.create("premier")
    second = await harness.projects.create("second")
    assert [p.id for p in await harness.projects.list()] == [second.id, first.id]


# --- Journal d'événements --------------------------------------------------------------------


def message(text: str) -> EventData:
    return MessageData(role="user", text=text)


async def test_a_second_log_rereads_the_history_and_continues_at_the_next_seq(
    harness: Harness,
) -> None:
    project, turn = await new_project(harness), uuid4()
    for text in ("un", "deux", "trois"):
        await harness.events.append(project, turn, message(text))

    reopened = harness.reopen_events()  # redéploiement : nouveau processus, même base
    history = await reopened.read_after(project, 0)
    assert [(e.seq, e.data.text) for e in history] == [(1, "un"), (2, "deux"), (3, "trois")]  # type: ignore[union-attr]
    assert [e.seq for e in await reopened.read_after(project, 2)] == [3]
    assert (await reopened.append(project, turn, message("quatre"))).seq == 4
    assert await reopened.read_after(await new_project(harness), 0) == []  # autre projet : vide


async def test_open_questions_are_read_back_by_a_second_store(harness: Harness) -> None:
    project = await new_project(harness)
    questions = [
        ClarificationQuestion(
            id="q1-1",
            field="environment",
            prompt="Quel environnement ?",
            options=["staging"],
            status="answered",
            answer="staging",
        ),
        ClarificationQuestion(id="q1-2", field="stack", prompt="Quelle stack ?", status="open"),
    ]
    await harness.projects.set_open_questions(project, questions)

    reopened = harness.reopen_projects()  # redémarrage : nouveau processus, même base
    assert list(await reopened.get_open_questions(project)) == questions
    assert list(await reopened.get_open_questions(await new_project(harness))) == []
    with pytest.raises(UnknownProject):
        await reopened.set_open_questions(uuid4(), questions)


async def test_concurrent_appends_stay_contiguous_and_reach_the_subscriber_in_order(
    harness: Harness,
) -> None:
    project, turn = await new_project(harness), uuid4()
    subscription = harness.events.subscribe(project)
    appended = await asyncio.gather(
        *(harness.events.append(project, turn, message(str(n))) for n in range(20))
    )
    assert sorted(e.seq for e in appended) == list(range(1, 21))  # aucun trou, aucun doublon
    delivered = [(await subscription.next()) for _ in range(20)]
    assert [e.seq for e in delivered if e is not None] == list(range(1, 21))  # ordre de seq
    assert [e.seq for e in await harness.events.read_after(project, 0)] == list(range(1, 21))
    subscription.close()
