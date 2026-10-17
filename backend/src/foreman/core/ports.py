"""Ports : interfaces définies par le cœur, implémentées par `infra` et `integrations`."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from foreman.core.events import AnyEvent, EventData
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


class Provider(Protocol):
    """Fournisseur de modèle. Sans état entre requêtes."""

    async def complete(self, messages: Sequence[str]) -> ModelReply: ...


class ProjectStore(Protocol):
    async def create(self, title: str) -> Project:
        """Lève `CapacityExceeded` si la borne de projets est atteinte."""
        ...

    async def get(self, project_id: UUID) -> Project | None: ...


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
