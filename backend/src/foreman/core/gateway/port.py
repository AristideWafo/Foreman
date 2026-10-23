"""Port de la gateway : tout ce que le moteur peut faire d'un outil passe par `Gateway.call`."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol
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


@dataclass(frozen=True, slots=True)
class ReadCall:
    """Une lecture directe demandée depuis le chat par `actor` (utilisateur), hors plan et hors
    exécution : la gateway relit le rôle de `actor` dans l'équipe du projet."""

    project_id: UUID
    actor: UUID
    tool: str
    params: Mapping[str, JsonValue]


ProbeVerdict = Literal["ok", "missing", "excess"]


@dataclass(frozen=True, slots=True)
class RightVerdict:
    """Verdict d'un droit : `ok` (prouvé), `missing` (la sonde échoue) ou `excess` (le jeton porte
    un scope non déclaré). `right` est le nom d'une sonde, ou d'un scope pour `excess`."""

    token: str
    right: str
    verdict: ProbeVerdict


@dataclass(frozen=True, slots=True)
class ProbeReport:
    """`incomplete` dès qu'un droit manque ; un droit `excess` seul n'empêche pas `complete`."""

    connector: str
    status: Literal["complete", "incomplete"]
    rights: tuple[RightVerdict, ...]


class Gateway(Protocol):
    # Suffixe de clé d'idempotence propre à cette instance d'adaptateurs non durables (faux en
    # mémoire, voir `ToolAdapter`) : amnésiques au redémarrage, pas de rejeu d'un ancien résultat.
    idempotency_scope: str

    async def call(self, call: GatewayCall) -> GatewayResult:
        """Exécute l'appel s'il passe les contrôles.

        Rejeu : tant que `complete_step` n'a pas marqué l'étape réussie, un appel séquentiel de la
        même étape (le moteur a échoué après la gateway) relance l'adaptateur. L'idempotence de
        l'adaptateur (clé `idempotency_key`) est donc REQUISE ; seuls deux appels simultanés de la
        même étape sont refusés (`call_in_progress`).

        Lève `CallDenied` (refus, adaptateur non appelé) ou `CallFailed` (échec d'exécution) ; ces
        deux cas sont déjà audités par la gateway. Les messages sont opaques. Toute autre
        exception est un défaut : le moteur finit alors l'exécution en `blocked`.
        """
        ...

    async def probe(self, connector: str, actor: UUID) -> ProbeReport:
        """Exécute les sondes déclarées du connecteur (lecture seule) pour `actor`.

        Le rôle est relu en base : `org_admin` requis. Lève `ProbeDenied` (rôle, limite, connecteur
        inconnu) ou `CallFailed` (échec d'une sonde) ; tout est audité (`tool="<c>.probe"`), sans
        jeton ni détail. Le statut du connecteur est mémorisé : un outil dépendant d'un droit
        manquant est ensuite refusé par `call` (`permission_missing`).
        """
        ...

    async def read(self, call: ReadCall) -> dict[str, JsonValue]:
        """Exécute un outil de classe `read` pour `actor` et rend sa sortie filtrée.

        Refuse (`CallDenied`) tout outil d'une autre classe, un acteur hors de l'équipe du projet
        et une lecture que la matrice (règle R1, niveau 1) n'autorise pas dans CHAQUE
        environnement. Une ligne d'audit par lecture (sans contenu) ; si elle ne s'écrit pas, la
        lecture n'est pas rendue (`CallFailed`).
        """
        ...
