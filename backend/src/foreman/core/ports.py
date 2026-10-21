"""Ports : interfaces définies par le cœur, implémentées par `infra` et `integrations`."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import JsonValue

from foreman.core.events import AnyEvent, ClarificationQuestion, EventData
from foreman.core.identity import Member, Role
from foreman.core.pricing import Usage
from foreman.core.projects import Project


class CapacityExceeded(Exception):
    """Une borne du stockage est atteinte (aucun détail interne dans le message)."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelReply:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage | None = None  # absent pour le rejeu : aucun coût


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Un message de l'historique envoyé au modèle (le dernier est celui du tour courant)."""

    role: Literal["user", "assistant"]
    text: str


class Provider(Protocol):
    """Fournisseur de modèle. Sans état entre requêtes : l'historique vient de l'appelant."""

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply: ...


@dataclass(frozen=True, slots=True)
class AdapterDiagnostic:
    """Ce qu'un adaptateur sait de son échec, en champs typés (zone non fiable : la gateway valide,
    masque et borne). `code` : un code normalisé (`port_in_use`, `image_not_found`...) ; `probe` :
    la sonde de vérification après action a réussi (`True`) ou échoué (`False`)."""

    code: str
    expected: str | int | bool | None = None
    observed: str | int | bool | None = None
    probe: bool | None = None
    # Sortie brute de l'échec : jamais transmise telle quelle, la gateway en tire un extrait.
    logs: tuple[str, ...] = ()


class AdapterError(Exception):
    """Un adaptateur a échoué. Le message est interne : la gateway ne le transmet pas tel quel.

    `diagnostic` (facultatif) est la seule partie qui atteint le modèle, une fois validée."""

    def __init__(self, message: str = "", diagnostic: AdapterDiagnostic | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


class ForeignResource(AdapterError):
    """La ressource visée existe mais n'est pas marquée `managed-by=foreman` : non adoptée."""


class PermissionMissing(AdapterError):
    """Le connecteur n'a pas le droit demandé (par exemple un jeton sans portée d'écriture)."""

    def __init__(self, connector: str, scope: str) -> None:
        super().__init__(f"permission manquante : {connector} / {scope}")
        self.connector = connector
        self.scope = scope


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Résultat d'un outil : `output` suit le schéma de sortie de l'outil, `logs` est brut.

    Les logs ne sont ni masqués ni tronqués ici : la gateway le fait avant toute sortie.

    `created` : vrai si l'appel a CRÉÉ la ressource, faux si elle existait déjà (retrouvée). Un
    outil `write_registry` de portée `create` (hors mode `check`) doit le dire : `None` est refusé
    par la gateway (`invalid_output`). Sans objet pour les autres outils.
    """

    output: dict[str, JsonValue]
    logs: list[str] = field(default_factory=list)
    created: bool | None = None


class ToolAdapter(Protocol):
    """Exécute UN outil d'un connecteur. Appelé uniquement par la gateway, après ses contrôles.

    - `tool` est le nom complet du catalogue (`gitlab.create_group`) ; un outil que le connecteur
      ne fournit pas lève `AdapterError`.
    - `params` est déjà validé par le schéma de l'outil ; la sûreté ne repose pas sur lui.
    - `idempotency_key` est la clé de l'étape : la rejouer ne produit aucun effet de plus et renvoie
      le même résultat (la sémantique exacte, `lookup_then_create` ou `return_previous_result`,
      est déclarée dans la définition de l'outil).
    - La gateway garantit qu'une même clé n'est utilisée que pour l'appel identique de l'étape
      du plan : un adaptateur peut donc rejouer sans comparer les paramètres.
    - Une même clé peut être rejouée tant que le moteur n'a pas enregistré la réussite de l'étape
      (panne entre l'appel et `complete_step`) : l'idempotence est REQUISE de l'adaptateur.
    - Attribut OPTIONNEL `epoch: str` : un adaptateur dont l'état ne survit pas au processus (faux
      en mémoire) déclare un identifiant propre à l'instance. La gateway l'ajoute à la clé
      d'idempotence : après un redémarrage, un résultat réservé avant n'est pas rejoué. Absent pour
      un adaptateur durable ou réel.
    - Aucun appel bloquant : un adaptateur réel déporte son travail hors de la boucle asynchrone.
    - Lève `AdapterError` (ou `PermissionMissing`) ; toute autre exception est un défaut.
    """

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult: ...


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """Résultat d'UNE sonde : `ok` (le droit est prouvé) et les scopes que la sonde a révélés
    (vide si elle n'en révèle aucun). Jamais de valeur de jeton."""

    ok: bool
    scopes: frozenset[str] = frozenset()
    # Valeurs observées (ex. `access_level`), comparées à `expects` de la sonde par la gateway.
    observed: Mapping[str, int] | None = None


@runtime_checkable
class ConnectorProber(Protocol):
    """Exécute les sondes DÉCLARÉES d'un connecteur. Appelé uniquement par `Gateway.probe`.

    - `call` est la ligne déclarée (`GET /groups?per_page=1`), validée en lecture seule au
      chargement du catalogue : une sonde n'écrit jamais, elle vérifie un scope ou un accès.
    - `token` est le NOM du jeton déclaré (`read`, `write`) ; l'adaptateur détient le secret.
    - Un droit refusé par le fournisseur (403) rend `ProbeOutcome(ok=False)` ; `PermissionMissing`
      est aussi compris comme un droit manquant. Toute autre erreur est un échec de sonde.
    - Aucun appel bloquant dans la boucle asynchrone.
    """

    async def probe(self, token: str, name: str, call: str) -> ProbeOutcome: ...


class ProjectStore(Protocol):
    async def create(self, title: str, team_id: UUID, created_by: UUID) -> Project:
        """Lève `CapacityExceeded` si la borne de projets est atteinte."""
        ...

    async def get(self, project_id: UUID) -> Project | None: ...

    async def list(self, team_ids: Collection[UUID] | None = None) -> list[Project]:
        """Les projets des équipes données (`None` : tous), du plus récent au plus ancien
        (bornés par la capacité du magasin)."""
        ...

    async def get_open_questions(self, project_id: UUID) -> Sequence[ClarificationQuestion]:
        """Questions de clarification du projet (ouvertes, répondues, reportées) ; `[]` si aucune
        ou si le projet est inconnu. Relues après un redémarrage en mode PostgreSQL."""
        ...

    async def set_open_questions(
        self, project_id: UUID, questions: Sequence[ClarificationQuestion]
    ) -> None:
        """Remplace les questions du projet. Lève `UnknownProject` si le projet n'existe pas."""
        ...


class Subscription(Protocol):
    """Abonnement au direct d'un projet. `next` renvoie `None` quand le flux est fermé."""

    async def next(self) -> AnyEvent | None: ...

    def close(self) -> None: ...


class RawLogStore(Protocol):
    """Log brut des échecs sans code connu : côté serveur, lu par l'humain habilité seulement.

    Jamais écrit dans le flux d'événements ni lu par le modèle."""

    def put(
        self, project_id: UUID, execution_id: UUID, step: int, lines: Sequence[str]
    ) -> None: ...

    def get(self, project_id: UUID, execution_id: UUID, step: int) -> Sequence[str] | None: ...


class EventLog(Protocol):
    """Journal d'événements par projet. `seq` est assigné par le journal (contigu dès 1)."""

    async def append(self, project_id: UUID, turn_id: UUID, data: EventData) -> AnyEvent: ...

    async def read_after(self, project_id: UUID, seq: int) -> list[AnyEvent]:
        """Événements conservés de `seq` strictement supérieur, dans l'ordre."""
        ...

    def has_subscriber_capacity(self, project_id: UUID) -> bool:
        """Vrai si un abonné de plus est accepté (plafond par projet et plafond global)."""
        ...

    def subscribe(self, project_id: UUID) -> Subscription:
        """Synchrone : l'inscription doit précéder la lecture de l'historique.

        Lève `CapacityExceeded` si un plafond d'abonnés est atteint.
        """
        ...


class MemberStore(Protocol):
    """Rôles des membres, PAR équipe. `org_admin` est global."""

    async def role_in(self, user_id: UUID, team_id: UUID) -> Role | None:
        """`org_admin` si le compte l'est (partout), sinon son rôle dans l'équipe, sinon `None`.
        Un compte désactivé n'a aucun rôle."""
        ...

    async def team_exists(self, team_id: UUID) -> bool: ...

    async def teams_of(self, user_id: UUID) -> frozenset[UUID] | None:
        """Équipes du compte ; `None` pour un `org_admin` (toutes)."""
        ...

    async def personal_team_of(self, user_id: UUID) -> UUID | None:
        """Équipe personnelle du compte, si elle existe."""
        ...

    async def designated_admins(self, team_id: UUID) -> frozenset[UUID] | None:
        """Équipe personnelle : comptes (hors org_admin) qui valident les plans de son
        propriétaire, soit l'inviteur actif et admin le plus proche (vide : repli org_admin).
        `None` pour une équipe non personnelle (les rôles de l'équipe décident)."""
        ...

    async def name_of(self, user_id: UUID) -> str | None:
        """Nom du membre (carte d'approbation), ou `None` s'il est inconnu."""
        ...

    async def sync(self, members: Sequence[Member]) -> None:
        """REMPLACE l'ensemble des membres : un nom retiré perd son rôle."""
        ...


async def requester_role(
    projects: ProjectStore, members: MemberStore, user_id: UUID | None, project_id: UUID
) -> Role | None:
    """Rôle du DEMANDEUR d'un plan dans l'équipe du projet (fermé par défaut : `None`)."""
    if user_id is None:
        return None
    project = await projects.get(project_id)
    return None if project is None else await members.role_in(user_id, project.team_id)
