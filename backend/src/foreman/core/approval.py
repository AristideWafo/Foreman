"""Approbation d'un plan par le développeur : décision atomique, puis cartes réémises.

Le dépôt (`PlanStore.approve`) porte l'atomicité : approbation, plan `dev_approved`, exécution et
étapes `pending` en une transaction. Ce service ajoute le contrôle de la matrice (pas
d'approbation d'administrateur requise) puis émet, dans l'ordre du contrat, la carte plan
réémise (`dev_approved`, `approvable: false`) AVANT la carte d'exécution.
"""

import logging
from uuid import UUID

from pydantic import ValidationError

from foreman.core.catalog import Catalog
from foreman.core.execution.cards import execution_card
from foreman.core.planning import PlanContent, plan_card, plan_card_id
from foreman.core.ports import EventLog
from foreman.core.store import (
    DEV_USER_ID,
    ApprovalRefused,
    ApprovalResult,
    Approved,
    Stores,
)

log = logging.getLogger(__name__)


class ApprovalService:
    def __init__(self, catalog: Catalog, stores: Stores, events: EventLog) -> None:
        self._catalog = catalog
        self._stores = stores
        self._events = events

    async def approve(self, project_id: UUID, plan_id: UUID, plan_hash: str) -> ApprovalResult:
        """Lève `StoreError` si le stockage est indisponible (aucun détail)."""
        plan = await self._stores.plans.get(project_id, plan_id)
        if plan is None:
            return ApprovalRefused("not_found")
        try:
            content = PlanContent.model_validate(plan.content)
        except ValidationError:
            return ApprovalRefused("plan_not_approvable")
        environment = self._catalog.policy.autonomy.environments.get(content.environment)
        if environment is None or environment.admin_approval_required:
            return ApprovalRefused("plan_not_approvable")  # la validation d'un admin viendra en S10
        result = await self._stores.plans.approve(
            project_id, plan_id, plan_hash, DEV_USER_ID, content.autonomy_level
        )
        if isinstance(result, Approved) and result.created:
            await self._announce(project_id, plan_id, result.execution_id, content)
        return result

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
