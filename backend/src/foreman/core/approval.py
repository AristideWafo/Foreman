"""Approbation d'un plan : validation du développeur, puis approbation d'un administrateur.

Le dépôt (`PlanStore`) porte l'atomicité : chaque décision est une transaction. Ce service ajoute
l'autorisation (qui peut décider : section `approvers` de la matrice) et le contrôle préalable de
la validation développeur (D2) : la matrice est évaluée sur CHAQUE étape avec le rôle du
DEMANDEUR ; on réunit les exigences. S'il manque `admin_approved`, la validation est écrite SANS
créer d'exécution, la carte d'approbation `pending` est émise et l'appelant répond 202.
L'approbation admin crée alors l'exécution (évaluée par la gateway avec le rôle du demandeur).

Cartes émises, dans l'ordre du contrat : la carte plan réémise AVANT la carte d'exécution.
Une carte non émise n'annule jamais la décision déjà écrite.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from pydantic import ValidationError

from foreman.core.catalog import Catalog
from foreman.core.events import ApprovalCardData, UserRef
from foreman.core.execution.cards import execution_card
from foreman.core.identity import Principal, Role
from foreman.core.planning import PlanContent, plan_card, plan_card_id
from foreman.core.policy.matrix import Deny, PolicyRequest, effective_level, evaluate, requirements
from foreman.core.ports import EventLog, MemberStore
from foreman.core.store import (
    AdminApprovalResult,
    AdminRejectionResult,
    ApprovalRefused,
    ApprovalResult,
    Approved,
    AwaitingAdmin,
    PlanRecord,
    Rejected,
    Stores,
)

log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def approval_card_id(plan_id: UUID) -> str:
    """Déterministe : la carte réémise (approuvée ou refusée) remplace la carte `pending`."""
    return f"approval-{plan_id.hex}"


class ApprovalService:
    def __init__(
        self,
        catalog: Catalog,
        stores: Stores,
        events: EventLog,
        members: MemberStore,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._catalog = catalog
        self._stores = stores
        self._events = events
        self._members = members
        self._clock = clock

    async def approve(
        self, project_id: UUID, plan_id: UUID, plan_hash: str, approver: Principal
    ) -> ApprovalResult:
        """Validation du développeur. Lève `StoreError` si le stockage est indisponible."""
        if approver.role not in self._catalog.policy.approvers.developer:
            return ApprovalRefused("forbidden")  # rien n'est écrit
        plan = await self._stores.plans.get(project_id, plan_id)
        if plan is None:
            return ApprovalRefused("not_found")
        try:
            content = PlanContent.model_validate(plan.content)
        except ValidationError:
            return ApprovalRefused("plan_not_approvable")
        if content.environment not in self._catalog.policy.autonomy.environments:
            await self._reissue_plan_card(project_id, plan, content)
            return ApprovalRefused("plan_not_approvable")
        precheck = await self._precheck(plan, content)
        if isinstance(precheck, ApprovalRefused):
            return precheck
        result = await self._stores.plans.approve(
            project_id,
            plan_id,
            plan_hash,
            approver.user_id,
            content.autonomy_level,
            start_execution=precheck is None,
        )
        if isinstance(result, Approved) and result.created:
            await self._announce(project_id, plan_id, result.execution_id, content)
        elif isinstance(result, AwaitingAdmin) and result.created:
            await self._announce_pending(project_id, plan, content, str(precheck))
        elif isinstance(result, ApprovalRefused) and result.reason != "not_found":
            # Le front attend la carte plan réémise plutôt que de deviner l'état après un 409.
            current = await self._stores.plans.get(project_id, plan_id)
            await self._reissue_plan_card(project_id, current or plan, content)
        return result

    async def approve_admin(
        self, project_id: UUID, plan_id: UUID, plan_hash: str, approver: Principal
    ) -> AdminApprovalResult:
        """Approbation d'un administrateur : crée l'exécution (que l'appelant démarre)."""
        if approver.role not in self._catalog.policy.approvers.admin:
            return ApprovalRefused("forbidden")  # rien n'est écrit
        loaded = await self._load(project_id, plan_id)
        if isinstance(loaded, ApprovalRefused):
            return loaded
        plan, content = loaded
        result = await self._stores.plans.approve_admin(
            project_id,
            plan_id,
            plan_hash,
            approver.user_id,
            approver.role,
            content.autonomy_level,
        )
        if isinstance(result, Approved) and result.created:
            await self._announce_decision(project_id, plan, content, "approved", approver)
            await self._announce(project_id, plan_id, result.execution_id, content)
        elif isinstance(result, ApprovalRefused) and result.reason != "not_found":
            current = await self._stores.plans.get(project_id, plan_id)
            await self._reissue_plan_card(project_id, current or plan, content)
        return result

    async def reject_admin(
        self, project_id: UUID, plan_id: UUID, plan_hash: str, approver: Principal
    ) -> AdminRejectionResult:
        """Refus d'un administrateur (D6) : plan `invalidated`, carte d'approbation `rejected`."""
        if approver.role not in self._catalog.policy.approvers.admin:
            return ApprovalRefused("forbidden")
        loaded = await self._load(project_id, plan_id)
        if isinstance(loaded, ApprovalRefused):
            return loaded
        plan, content = loaded
        result = await self._stores.plans.reject_admin(
            project_id, plan_id, plan_hash, approver.user_id, approver.role
        )
        if isinstance(result, Rejected) and result.created:
            await self._announce_decision(project_id, plan, content, "rejected", approver)
            current = await self._stores.plans.get(project_id, plan_id)
            await self._reissue_plan_card(project_id, current or plan, content)
        return result

    async def _load(
        self, project_id: UUID, plan_id: UUID
    ) -> tuple[PlanRecord, PlanContent] | ApprovalRefused:
        plan = await self._stores.plans.get(project_id, plan_id)
        if plan is None:
            return ApprovalRefused("not_found")
        try:
            return plan, PlanContent.model_validate(plan.content)
        except ValidationError:
            return ApprovalRefused("plan_not_approvable")

    async def _precheck(
        self, plan: PlanRecord, content: PlanContent
    ) -> ApprovalRefused | str | None:
        """Matrice évaluée sur chaque étape avec le rôle du demandeur (D2).

        Rend l'identifiant de la règle qui exige `admin_approved` (l'exécution attendra l'admin),
        `None` si aucune étape ne l'exige, ou un refus `policy_denied` si une étape est interdite
        au demandeur (par exemple R8 pour un développeur) ou si le demandeur est inconnu.
        """
        role = None if plan.requested_by is None else await self._members.role_of(plan.requested_by)
        if role is None:
            return ApprovalRefused("policy_denied")
        matrix = self._catalog.policy
        level = effective_level(matrix, content.environment, content.autonomy_level)
        admin_rule: str | None = None
        for step in content.steps:
            verdict = evaluate(
                matrix,
                PolicyRequest(
                    tool_class=step.tool_class,
                    environment=content.environment,
                    reversibility=step.reversibility,
                    role=role,
                    level=level,
                ),
            )
            if isinstance(verdict, Deny):
                return ApprovalRefused("policy_denied")
            needed = requirements(matrix, verdict, content.environment)
            if "admin_approved" in needed and admin_rule is None:
                admin_rule = verdict.rule_id
        return admin_rule

    async def _reissue_plan_card(
        self, project_id: UUID, record: PlanRecord, content: PlanContent
    ) -> None:
        """Carte plan telle que l'état persisté la décrit. `expired` n'est jamais écrit en base :
        un plan proposé dont l'échéance est passée s'affiche `expired`, non approuvable."""
        try:
            if record.status == "proposed" and record.expires_at <= self._clock():
                record = replace(record, status="expired")
            card = plan_card(record, content, self._catalog, plan_card_id(record.id))
            await self._events.append(project_id, record.id, card)  # turn_id = plan_id
        except Exception as exc:
            log.warning("approbation %s : carte non réémise (%s)", record.id, type(exc).__name__)

    async def _announce(
        self, project_id: UUID, plan_id: UUID, execution_id: UUID, content: PlanContent
    ) -> None:
        """Ne lève jamais : l'approbation est écrite, l'exécution doit partir quoi qu'il arrive."""
        try:
            record = await self._stores.plans.get(project_id, plan_id)
            if record is not None:
                card = plan_card(record, content, self._catalog, plan_card_id(plan_id))
                await self._events.append(project_id, execution_id, card)
            execution = await execution_card(self._stores, self._catalog, project_id, execution_id)
            if execution is not None:
                await self._events.append(project_id, execution_id, execution)
        except Exception as exc:
            log.warning("approbation %s : cartes non émises (%s)", plan_id, type(exc).__name__)

    async def _announce_pending(
        self, project_id: UUID, plan: PlanRecord, content: PlanContent, rule_id: str
    ) -> None:
        """Plan réémis (`dev_approved`, plus approuvable) puis carte d'approbation `pending`."""
        current = await self._stores.plans.get(project_id, plan.id)
        await self._reissue_plan_card(project_id, current or plan, content)
        await self._emit_approval_card(project_id, plan, content, "pending", None, rule_id)

    async def _announce_decision(
        self,
        project_id: UUID,
        plan: PlanRecord,
        content: PlanContent,
        status: Literal["approved", "rejected"],
        approver: Principal,
    ) -> None:
        rule = await self._precheck(plan, content)  # la règle qui exigeait l'admin
        await self._emit_approval_card(
            project_id,
            plan,
            content,
            status,
            UserRef(name=approver.name),
            rule if isinstance(rule, str) else "inconnue",
        )

    async def _emit_approval_card(
        self,
        project_id: UUID,
        plan: PlanRecord,
        content: PlanContent,
        status: Literal["pending", "approved", "rejected"],
        decided_by: UserRef | None,
        rule_id: str,
    ) -> None:
        """Ne lève jamais : la décision est écrite, la carte est un affichage."""
        try:
            requester = (
                None
                if plan.requested_by is None
                else await self._members.name_of(plan.requested_by)
            )
            card = ApprovalCardData(
                card_id=approval_card_id(plan.id),
                kind="approval",
                plan_id=plan.id,
                plan_hash=plan.content_hash,
                plan_card_id=plan_card_id(plan.id),
                environment=content.environment,
                rule_id=rule_id,
                missing=["admin_approved"] if status == "pending" else [],
                approver_roles=cast(list[Role], list(self._catalog.policy.approvers.admin)),
                requested_by=UserRef(name=requester or "inconnu"),
                status=status,
                decided_by=decided_by,
            )
            await self._events.append(project_id, plan.id, card)  # turn_id = plan_id
        except Exception as exc:
            log.warning("approbation %s : carte non émise (%s)", plan.id, type(exc).__name__)
