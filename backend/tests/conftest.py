"""Fixtures partagées : une base PostgreSQL NEUVE par test (créée puis supprimée)."""

import os
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from foreman.config.env import ENV_TEST_DATABASE_URL


def _admin_url() -> str:
    url = os.environ.get(ENV_TEST_DATABASE_URL)
    if url:
        return url
    reason = f"{ENV_TEST_DATABASE_URL} non défini : tests PostgreSQL ignorés"
    if os.environ.get("CI") == "true":
        pytest.fail(reason + " (interdit en CI)", pytrace=False)
    pytest.skip(reason)


@pytest.fixture
def new_database() -> Iterator[Callable[[], str]]:
    """Fabrique de bases vides ; toutes sont supprimées en fin de test (même si des connexions
    traînent). Le test ne voit jamais l'URL d'origine."""
    admin_url = _admin_url()
    names: list[str] = []
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)

    def create() -> str:
        name = f"foreman_t_{uuid.uuid4().hex[:16]}"
        with engine.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
        names.append(name)
        return make_url(admin_url).set(database=name).render_as_string(hide_password=False)

    try:
        yield create
    finally:
        with engine.connect() as conn:
            for name in names:
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()


@pytest.fixture
def blank_database_url(new_database: Callable[[], str]) -> str:
    return new_database()
