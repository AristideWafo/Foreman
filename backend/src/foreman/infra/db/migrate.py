"""Point d'entrée unique des migrations. `upgrade_head` est bloquant : `asyncio.to_thread`.

Un verrou consultatif de session est pris avant Alembic : deux instances qui démarrent ensemble
s'exécutent l'une après l'autre, la seconde ne trouve plus rien à faire. Les migrations
s'exécutent dans une transaction (DDL transactionnel de PostgreSQL) : un échec ne laisse rien.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

# Constante arbitraire propre à Foreman (clé du verrou consultatif).
MIGRATION_LOCK_KEY = 7_361_530_001
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


@contextmanager
def _locked_connection(url: str) -> Iterator[sa.Connection]:
    """Connexion de migration, sous verrou consultatif (connexion dédiée, hors transaction)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool, echo=False)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock_conn:
            lock_conn.execute(sa.text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
            try:
                with engine.connect() as conn:
                    yield conn
                    conn.commit()
            finally:
                lock_conn.execute(
                    sa.text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY}
                )
    finally:
        engine.dispose()


def _run(url: str, action: Callable[[Config], None]) -> None:
    with _locked_connection(url) as conn:
        action(alembic_config(conn))


def upgrade_head(url: str) -> None:
    _run(url, lambda config: command.upgrade(config, "head"))


def downgrade(url: str, revision: str) -> None:
    """Retour arrière (tests, opérations manuelles), sous le même verrou."""
    _run(url, lambda config: command.downgrade(config, revision))
