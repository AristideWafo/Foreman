"""Base du plan (S12, D1/D2) : un registre ou un catalogue modifié depuis la proposition n'est
jamais approuvé, ni par le développeur ni par l'administrateur, et ne crée aucune exécution."""

import dataclasses
from uuid import UUID, uuid4

import pytest

from foreman.core.approval import ApprovalService, approval_card_id
from foreman.core.identity import Principal
from foreman.core.planning import Draft, DraftStep, Planner
from foreman.core.store import DEV_USER_ID, ApprovalRefused, Approved, AwaitingAdmin, ResourceRecord
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, in_memory_stores
from support import DEV_PRINCIPAL, dev_members

ADMIN = Principal(user_id=uuid4(), name="admin", role="team_admin")
DRAFT = Draft(
    title="Groupe",
    summary="Un groupe",
    environment="production",
    steps=[
        DraftStep(
            "Racine", "gitlab.create_group", {"parent_group_id": 1000, "name": "A", "path": "aa"}
        )
    ],
)


async def setup(catalog_changed: bool = False):
    catalog = load_catalog(environment="staging")
    state, stores = in_memory_stores()
    events, project = InMemoryEventLog(), uuid4()
    record, _ = await Planner(catalog, stores.plans, stores.registry).propose(
        project, DRAFT, DEV_USER_ID
    )
    served = (
        dataclasses.replace(catalog, policy_sha256="sha256:" + "0" * 64)
        if catalog_changed
        else catalog
    )
    service = ApprovalService(served, stores, events, dev_members())
    return state, stores, events, project, record, service


def add_resource(state, project: UUID) -> None:
    state.resources[("gitlab", "group", "42")] = ResourceRecord(
        uuid4(), project, None, "gitlab", "group", "42", None, "created"
    )


async def no_execution(stores) -> bool:
    return not await stores.executions.list_resumable()


async def test_unchanged_plan_stays_approvable() -> None:
    _, _, _, project, record, service = await setup()
    first = await service.approve(project, record.id, record.content_hash, DEV_PRINCIPAL)
    assert isinstance(first, AwaitingAdmin)
    second = await service.approve_admin(project, record.id, record.content_hash, ADMIN)
    assert isinstance(second, Approved)


@pytest.mark.parametrize(
    ("catalog_changed", "reason"), [(False, "project_changed"), (True, "catalog_changed")]
)
async def test_changed_basis_is_never_approved_by_dev_nor_admin(
    catalog_changed: bool, reason: str
) -> None:
    state, stores, events, project, record, service = await setup(catalog_changed)
    if not catalog_changed:
        add_resource(state, project)
    refusal = ApprovalRefused("plan_not_approvable")
    for _ in range(2):  # le rejeu donne toujours 409
        assert (
            await service.approve(project, record.id, record.content_hash, DEV_PRINCIPAL) == refusal
        )
        assert (
            await service.approve_admin(project, record.id, record.content_hash, ADMIN) == refusal
        )
    plan = await stores.plans.get(project, record.id)
    assert plan is not None and plan.status == "invalidated"
    assert plan.invalidation is not None and plan.invalidation["reason"] == reason
    assert await no_execution(stores)
    cards = [e.data for e in await events.read_after(project, 0)]
    assert [c.status for c in cards if c.kind == "plan"] == ["invalidated"]  # une seule fois


async def test_registry_change_after_dev_approval_invalidates_both_cards() -> None:
    state, stores, events, project, record, service = await setup()
    assert isinstance(
        await service.approve(project, record.id, record.content_hash, DEV_PRINCIPAL), AwaitingAdmin
    )
    add_resource(state, project)
    for _ in range(2):
        result = await service.approve_admin(project, record.id, record.content_hash, ADMIN)
        assert result == ApprovalRefused("plan_not_approvable")
    assert await no_execution(stores)
    latest = {e.data.card_id: e.data.status for e in await events.read_after(project, 0)}
    assert latest[approval_card_id(record.id)] == "invalidated"
    assert latest[record.id.hex] == "invalidated"


async def test_admin_replay_stays_idempotent_after_registry_changes() -> None:
    state, stores, events, project, record, service = await setup()
    await service.approve(project, record.id, record.content_hash, DEV_PRINCIPAL)
    first = await service.approve_admin(project, record.id, record.content_hash, ADMIN)
    assert isinstance(first, Approved) and first.created
    cards = len(await events.read_after(project, 0))
    add_resource(state, project)  # l'exécution elle-même change le registre
    again = await service.approve_admin(project, record.id, record.content_hash, ADMIN)
    assert isinstance(again, Approved) and not again.created
    assert len(await events.read_after(project, 0)) == cards
    plan = await stores.plans.get(project, record.id)
    assert plan is not None and plan.status != "invalidated"
