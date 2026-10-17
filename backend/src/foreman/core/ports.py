"""Ports : interfaces définies par le cœur, implémentées par `infra` et `integrations`."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelReply:
    text: str


class Provider(Protocol):
    """Fournisseur de modèle. Sans état entre requêtes."""

    async def complete(self, messages: Sequence[str]) -> ModelReply: ...
