"""Limite d'échecs en mémoire : 5 échecs / 15 min par clé, puis refus (429 générique)."""

import time
from collections.abc import Callable

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
MAX_KEYS = 10_000  # borne la mémoire face à un balayage d'adresses ou d'e-mails


class FailureLimiter:
    # shortcut: par processus, à remplacer si plusieurs conteneurs
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        floor = self._clock() - WINDOW_SECONDS
        recent = [t for t in self._failures.get(key, []) if t > floor]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def blocked(self, *keys: str) -> bool:
        return any(len(self._recent(k)) >= MAX_FAILURES for k in keys)

    def fail(self, *keys: str) -> None:
        for key in keys:
            if key not in self._failures and len(self._failures) >= MAX_KEYS:
                # Saturée : on vide (la limite se réarme) plutôt que de laisser la mémoire croître.
                self._failures.clear()
            self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
