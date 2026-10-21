"""Clé maître des secrets : création au premier démarrage, refus si elle manque, rotation."""

import logging

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.bootstrap.database import Lifecycle
from foreman.core.secrets import SecretStore
from foreman.infra.db import tables as t
from foreman.infra.secrets import KeyFile

log = logging.getLogger(__name__)


class SecretsLifecycle:
    """Après les migrations : charge la clé maître, ou la crée si la base ne contient aucun secret.

    Des secrets sans clé = clé perdue ou volume non monté : on refuse de démarrer plutôt que de
    générer une autre clé qui rendrait ces secrets définitivement illisibles.
    """

    def __init__(self, inner: Lifecycle, key_file: KeyFile, engine: AsyncEngine) -> None:
        self._inner = inner
        self._key_file = key_file
        self._engine = engine

    async def start(self) -> None:
        await self._inner.start()
        if not self._key_file.exists():
            async with self._engine.connect() as conn:
                stored = (
                    await conn.execute(sa.select(sa.func.count()).select_from(t.secrets))
                ).scalar_one()
            if stored:
                raise RuntimeError(
                    "clé maître des secrets absente alors que des secrets existent : "
                    "restaurer le volume de la clé (docs/DEPLOYMENT.md)"
                )
            try:
                self._key_file.create()
                log.info("clé maître des secrets créée (premier démarrage)")
            except FileExistsError:
                pass  # une autre instance l'a créée entre-temps
        self._key_file.current()  # fichier illisible ou clé invalide : arrêt immédiat

    async def stop(self) -> None:
        await self._inner.stop()


async def rotate_master_key(key_file: KeyFile, store: SecretStore, *, prune: bool) -> int:
    """Ajoute une clé active (dans le fichier d'abord), rechiffre tout, puis retire les anciennes
    clés si `prune`. À lancer sans écriture concurrente de secrets quand `prune` est demandé."""
    key_file.add_key()
    count = await store.rotate()
    if prune:
        key_file.keep_only_active()
    return count
