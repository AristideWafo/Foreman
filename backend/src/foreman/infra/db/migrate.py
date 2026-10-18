"""Point d'entrée unique des migrations. `upgrade_head` est bloquant : `asyncio.to_thread`.

Un verrou consultatif de session est pris avant Alembic : deux instances qui démarrent ensemble
s'exécutent l'une après l'autre, la seconde ne trouve plus rien à faire. Les migrations
s'exécutent dans une transaction (DDL transactionnel de PostgreSQL) : un échec ne laisse rien.
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

# Constante arbitraire propre à Foreman (clé du verrou consultatif).
MIGRATION_LOCK_KEY = 7_361_530_001
LOCK_TIMEOUT_S = 60.0
LOCK_POLL_S = 0.2
log = logging.getLogger(__name__)
_INI = "alembic.ini"


def _backend_root() -> Path:
    """`alembic.ini` à côté de `migrations/` : dans l'image (WORKDIR) ou dans le dépôt."""
    for candidate in (Path.cwd(), Path(__file__).resolve().parents[4]):
        if (candidate / _INI).is_file():
            return candidate
    raise RuntimeError("alembic.ini introuvable")


def alembic_config(connection: sa.Connection | None = None) -> Config:
    root = _backend_root()
    config = Config(str(root / _INI))
    config.set_main_option("script_location", str(root / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def _acquire(lock_conn: sa.Connection, timeout_s: float) -> None:
    """Prend le verrou par interrogation bornée : un verrou orphelin ne bloque pas le démarrage."""
    deadline = time.monotonic() + timeout_s
    while True:
        got = lock_conn.execute(
            sa.text("SELECT pg_try_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY}
        ).scalar()
        if got:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"verrou de migration non obtenu en {timeout_s:g} s")
        time.sleep(LOCK_POLL_S)


@contextmanager
def _locked_connection(url: str, lock_timeout_s: float) -> Iterator[sa.Connection]:
    """Connexion de migration, sous verrou consultatif (connexion dédiée, hors transaction)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool, echo=False)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_conn:
            _acquire(lock_conn, lock_timeout_s)
            try:
                with engine.connect() as conn:
                    yield conn
                    conn.commit()
            finally:
                try:
                    lock_conn.execute(
                        sa.text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY}
                    )
                except Exception as exc:
                    # La fermeture de la connexion libère de toute façon le verrou de session.
                    log.warning("libération du verrou de migration : %s", type(exc).__name__)
    finally:
        engine.dispose()


def _run(url: str, lock_timeout_s: float, action: Callable[[Config], None]) -> None:
    with _locked_connection(url, lock_timeout_s) as conn:
        action(alembic_config(conn))


def upgrade_head(url: str, lock_timeout_s: float = LOCK_TIMEOUT_S) -> None:
    _run(url, lock_timeout_s, lambda config: command.upgrade(config, "head"))


def downgrade(url: str, revision: str, lock_timeout_s: float = LOCK_TIMEOUT_S) -> None:
    """Retour arrière (tests, opérations manuelles), sous le même verrou."""
    _run(url, lock_timeout_s, lambda config: command.downgrade(config, revision))
