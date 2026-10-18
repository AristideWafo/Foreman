"""Moteur asynchrone. L'URL ne sort jamais dans un journal (pas d'`echo`)."""

import logging

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

POOL_SIZE = 5
MAX_OVERFLOW = 5
POOL_TIMEOUT_S = 10
POOL_RECYCLE_S = 1_800

log = logging.getLogger(__name__)


def make_engine(url: str) -> AsyncEngine:
    """Pool borné, connexions testées avant usage. Transactions : `async with engine.begin()`."""
    return create_async_engine(
        url,
        echo=False,
        pool_size=POOL_SIZE,
        max_overflow=MAX_OVERFLOW,
        pool_timeout=POOL_TIMEOUT_S,
        pool_recycle=POOL_RECYCLE_S,
        pool_pre_ping=True,
    )


def constraint_of(exc: DBAPIError) -> str:
    """Nom de la contrainte violée (vide si inconnu). Jamais le message du pilote."""
    diag = getattr(exc.orig, "diag", None)
    return str(getattr(diag, "constraint_name", "") or "")


def log_failure(operation: str, exc: Exception) -> None:
    """Journal opaque : l'opération et le type d'erreur, ni SQL ni paramètres ni URL."""
    log.warning("échec de stockage (%s) : %s", operation, type(exc).__name__)
