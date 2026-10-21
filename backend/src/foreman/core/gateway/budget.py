"""Budget d'une exécution : appels, durée, essais par étape et coût du modèle.

En mémoire du processus, borné (les plus anciennes exécutions sont oubliées). Après un redémarrage
les compteurs repartent de zéro : accepté pour le PoC. Un essai est un appel de gateway qui a passé
tous les contrôles pour une étape ; la première tentative n'est pas un « nouvel essai ».
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import UUID

MAX_TRACKED_EXECUTIONS = 256

Exceeded = Literal["calls", "duration", "retries", "cost"]


@dataclass(slots=True)
class _Run:
    started: float
    calls: int = 0
    cost_eur: Decimal = Decimal(0)
    attempts: dict[int, int] = field(default_factory=dict)  # étape -> essais


class CallBudget:
    def __init__(
        self,
        max_calls: int,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = MAX_TRACKED_EXECUTIONS,
        max_retries_per_step: int | None = None,
        max_cost_eur: float | None = None,
    ) -> None:
        self._max_calls = max_calls
        self._max_seconds = max_seconds
        self._clock = clock
        self._max_tracked = max_tracked
        self._max_attempts = None if max_retries_per_step is None else max_retries_per_step + 1
        self._max_cost = None if max_cost_eur is None else Decimal(str(max_cost_eur))
        self._seen: OrderedDict[UUID, _Run] = OrderedDict()

    def _run(self, execution_id: UUID) -> _Run:
        run = self._seen.get(execution_id)
        if run is None:
            run = self._seen[execution_id] = _Run(self._clock())
        self._seen.move_to_end(execution_id)
        while len(self._seen) > self._max_tracked:
            self._seen.popitem(last=False)
        return run

    def refund(self, execution_id: UUID, step_seq: int | None = None) -> None:
        """Annule le comptage d'un appel qui n'a finalement pas eu lieu."""
        run = self._seen.get(execution_id)
        if run is None or run.calls == 0:
            return
        run.calls -= 1
        if step_seq is not None and run.attempts.get(step_seq):
            run.attempts[step_seq] -= 1

    def add_cost(self, execution_id: UUID, eur: Decimal) -> None:
        """Ajoute le coût d'un appel modèle fait pour cette exécution (jamais négatif)."""
        self._run(execution_id).cost_eur += max(eur, Decimal(0))

    def consume(self, execution_id: UUID, step_seq: int | None = None) -> Exceeded | None:
        """Compte un appel. Renvoie la limite atteinte (et rien n'est compté), ou `None`.

        Synchrone, sans point de suspension : la vérification et le comptage sont atomiques.
        """
        run = self._run(execution_id)
        if run.calls >= self._max_calls:
            return "calls"
        if self._clock() - run.started > self._max_seconds:
            return "duration"
        if self._max_cost is not None and run.cost_eur > self._max_cost:
            return "cost"
        attempts = 0 if step_seq is None else run.attempts.get(step_seq, 0)
        if self._max_attempts is not None and attempts >= self._max_attempts:
            return "retries"
        run.calls += 1
        if step_seq is not None:
            run.attempts[step_seq] = attempts + 1
        return None
