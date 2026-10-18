"""Budget d'une exécution : nombre d'appels et durée.

En mémoire du processus, borné (les plus anciennes exécutions sont oubliées). Après un redémarrage
le compteur repart de zéro : accepté pour le PoC. Les essais par étape et le coût du modèle ne
sont pas appliqués ici (aucun nouvel essai, aucun modèle en jeu pour l'instant).
"""

import time
from collections import OrderedDict
from collections.abc import Callable
from uuid import UUID

MAX_TRACKED_EXECUTIONS = 256


class CallBudget:
    def __init__(
        self,
        max_calls: int,
        max_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        max_tracked: int = MAX_TRACKED_EXECUTIONS,
    ) -> None:
        self._max_calls = max_calls
        self._max_seconds = max_seconds
        self._clock = clock
        self._max_tracked = max_tracked
        self._seen: OrderedDict[UUID, tuple[float, int]] = OrderedDict()

    def consume(self, execution_id: UUID) -> bool:
        """Compte un appel. Faux (et rien n'est compté) si le budget est épuisé.

        Synchrone, sans point de suspension : la vérification et le comptage sont atomiques.
        """
        now = self._clock()
        started, calls = self._seen.get(execution_id, (now, 0))
        if calls >= self._max_calls or now - started > self._max_seconds:
            return False
        self._seen[execution_id] = (started, calls + 1)
        self._seen.move_to_end(execution_id)
        while len(self._seen) > self._max_tracked:
            self._seen.popitem(last=False)
        return True
