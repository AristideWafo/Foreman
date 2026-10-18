"""Environnement Alembic. Une connexion fournie par `upgrade_head` (sous verrou) ou, en ligne de
commande, l'URL de `FOREMAN_DATABASE_URL`. Ne journalise jamais l'URL."""

import os

import sqlalchemy as sa
from alembic import context

from foreman.config.env import ENV_DATABASE_URL
from foreman.infra.db.tables import metadata

config = context.config
# Pas de `fileConfig` : il désactiverait les journaux de l'application qui lance la migration.


def _run(connection: sa.Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    url = os.environ.get(ENV_DATABASE_URL)
    if not url:
        raise RuntimeError(f"{ENV_DATABASE_URL} n'est pas défini")
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Le mode hors ligne n'est pas pris en charge")
run_migrations_online()
