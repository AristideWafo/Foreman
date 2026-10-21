"""Budget d'UN tour : appels au modèle, jetons, coût (EUR) et durée.

Un compteur par tour, jamais partagé. `admit` précède chaque appel au modèle et le compte ; `record`
ajoute le `usage` rapporté. Une fois une limite dépassée, `admit` refuse pour toujours : le modèle
n'est plus rappelé.
"""

import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Literal

from foreman.core.catalog import TurnBudget
from foreman.core.pricing import ModelPrice, Usage, cost_eur

TurnLimit = Literal["calls", "tokens", "cost", "duration"]


class UnpricedModel(Exception):
    """Le modèle n'a pas de tarif déclaré : le coût est inconnu, on ne continue pas."""


class TurnMeter:
    def __init__(
        self,
        limits: TurnBudget,
        prices: Mapping[str, ModelPrice],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._prices = prices
        self._clock = clock
        self._started = clock()
        self.calls = 0
        self.tokens = 0
        self.cost = Decimal(0)

    def over(self) -> TurnLimit | None:
        """La première limite DÉPASSÉE (pas seulement atteinte), ou `None`."""
        if self.tokens > self._limits.max_tokens:
            return "tokens"
        if self.cost > Decimal(str(self._limits.max_cost_eur)):
            return "cost"
        if self._clock() - self._started > self._limits.max_seconds:
            return "duration"
        return None

    def admit(self) -> TurnLimit | None:
        """Autorise (et compte) un appel au modèle, ou renvoie la limite qui l'interdit."""
        if (limit := self.over()) is not None:
            return limit
        if self.calls >= self._limits.max_model_calls:
            return "calls"
        self.calls += 1
        return None

    def record(self, usage: Usage | None) -> None:
        """Ajoute le `usage` d'un appel. Lève `UnpricedModel` si le modèle n'a pas de tarif."""
        if usage is None:
            return  # rejeu : ni jetons ni coût
        price = self._prices.get(usage.model)
        if price is None:
            raise UnpricedModel
        self.tokens += usage.total_tokens
        self.cost += cost_eur(usage, price)

    def summary(self, limit: TurnLimit) -> str:
        """Texte fixe pour l'utilisateur : ne contient que des nombres et des mots du code."""
        limits = self._limits
        used = {
            "calls": f"appels au modèle {self.calls} sur {limits.max_model_calls}",
            "tokens": f"jetons {self.tokens} sur {limits.max_tokens}",
            "cost": f"coût {self.cost:.4f} € sur {limits.max_cost_eur} €",
            "duration": f"durée dépassée ({limits.max_seconds} s)",
        }[limit]
        return f"Budget du tour dépassé ({used}). L'agent s'arrête sans autre action."
