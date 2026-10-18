"""Port de la gateway : tout ce que le moteur peut faire d'un outil passe par `Gateway.call`."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from foreman.core.store import AuditEntry, NewResource


@dataclass(frozen=True, slots=True)
class GatewayCall:
    """Un appel d'outil pour UNE étape d'une exécution.

    Le moteur ne fournit ni plan, ni rôle, ni classe d'outil : la gateway les relit en base. Elle
    refuse l'appel s'il diffère de l'étape `step_seq` du plan approuvé (`tool`, `params` une fois
    les références résolues, `idempotency_key`), si `plan_hash` n'est pas celui du plan, si le bail
    (`lease_owner`, `lease_epoch`) n'est plus valide, si l'étape n'a pas été réservée par
    `reserve_idempotency` (statut `running`) ou si une étape antérieure n'a pas réussi.
    """

    project_id: UUID
    execution_id: UUID
    step_seq: int
    plan_hash: str
    tool: str
    params: Mapping[str, JsonValue]  # références `$from` déjà résolues par le moteur
    idempotency_key: str
    lease_owner: str  # bail du moteur, revérifié par la gateway
    lease_epoch: int


@dataclass(frozen=True, slots=True)
class GatewayResult:
    """Résultat d'un appel exécuté, déjà filtré (secrets masqués, taille bornée).

    Le moteur transmet `resources` et `audit` tels quels à `ExecutionStore.complete_step` : étape,
    registre et audit s'écrivent dans la même transaction. `audit` est la ligne de RÉSULTAT
    (`decision="executed"`) ; la ligne de décision (`allow`) est écrite par la gateway AVANT
    l'exécution. `resources` ne contient que les ressources CRÉÉES (portée `create`).
    """

    output: dict[str, JsonValue]
    logs: list[str]  # au plus 50 lignes de 500 caractères
    resources: tuple[NewResource, ...]
    audit: AuditEntry


class Gateway(Protocol):
    async def call(self, call: GatewayCall) -> GatewayResult:
        """Exécute l'appel s'il passe les contrôles.

        Lève `CallDenied` (refus, adaptateur non appelé) ou `CallFailed` (échec d'exécution) ; ces
        deux cas sont déjà audités par la gateway. Les messages sont opaques. Toute autre
        exception est un défaut : le moteur finit alors l'exécution en `blocked`.
        """
        ...
