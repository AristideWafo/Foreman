"""Cycle de vie de la base : migrations au démarrage, identités de développement, fermeture.

L'URL de la base n'apparaît dans aucun journal ni dans aucune exception sortante.
"""

import asyncio
import logging
from typing import Protocol

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.store import StoreError
from foreman.infra.db.migrate import upgrade_head
from foreman.infra.db.projects import seed_dev_identity

log = logging.getLogger(__name__)

STARTUP_ATTEMPTS = 5
STARTUP_DELAY_S = 2.0


class Lifecycle(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class NoLifecycle:
    """Profils sans base (CLI, tests) : rien à démarrer."""

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class DatabaseLifecycle:
    def __init__(
        self,
        url: str,
        engine: AsyncEngine,
        attempts: int = STARTUP_ATTEMPTS,
        delay_s: float = STARTUP_DELAY_S,
    ) -> None:
        self._url = url
        self._engine = engine
        self._attempts = attempts
        self._delay_s = delay_s

    async def start(self) -> None:
        """Migrations sous verrou consultatif (hors boucle : Alembic est bloquant), puis amorçage.

        Reconnexions bornées : la base peut démarrer après l'application (déploiement Compose).
        """
        for attempt in range(1, self._attempts + 1):
            try:
                await asyncio.to_thread(upgrade_head, self._url)
                await seed_dev_identity(self._engine)
                return
            except (DBAPIError, StoreError, OSError) as exc:
                # Ni message ni trace : ils pourraient contenir l'adresse de la base.
                log.warning(
                    "base indisponible (%s), tentative %d/%d",
                    type(exc).__name__,
                    attempt,
                    self._attempts,
                )
                if attempt < self._attempts:
                    await asyncio.sleep(self._delay_s)
        raise RuntimeError("base de données indisponible au démarrage") from None

    async def stop(self) -> None:
        await self._engine.dispose()
