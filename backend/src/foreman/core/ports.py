"""Ports : interfaces définies par le cœur, implémentées par `infra` et `integrations`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol
from uuid import UUID

from pydantic import JsonValue

from foreman.core.events import AnyEvent, ClarificationQuestion, EventData
from foreman.core.identity import Member, Role
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


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    """Un message de l'historique envoyé au modèle (le dernier est celui du tour courant)."""

    role: Literal["user", "assistant"]
    text: str


class Provider(Protocol):
    """Fournisseur de modèle. Sans état entre requêtes : l'historique vient de l'appelant."""

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply: ...


class AdapterError(Exception):
    """Un adaptateur a échoué. Le message est interne : la gateway ne le transmet pas tel quel."""


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
    - Aucun appel bloquant : un adaptateur réel déporte son travail hors de la boucle asynchrone.
    - Lève `AdapterError` (ou `PermissionMissing`) ; toute autre exception est un défaut.
    """

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult: ...


class ProjectStore(Protocol):
    async def create(self, title: str) -> Project:
        """Lève `CapacityExceeded` si la borne de projets est atteinte."""
        ...

    async def get(self, project_id: UUID) -> Project | None: ...

    async def list(self) -> list[Project]:
        """Les projets, du plus récent au plus ancien (bornés par la capacité du magasin)."""
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
    """Rôles des membres de l'équipe de développement (une seule équipe au PoC)."""

    async def role_of(self, user_id: UUID) -> Role | None:
        """Rôle du membre, ou `None` s'il est inconnu."""
        ...

    async def name_of(self, user_id: UUID) -> str | None:
        """Nom du membre (carte d'approbation), ou `None` s'il est inconnu."""
        ...

    async def sync(self, members: Sequence[Member]) -> None:
        """REMPLACE l'ensemble des membres : un nom retiré perd son rôle."""
        ...
