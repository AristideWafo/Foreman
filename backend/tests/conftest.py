"""Fixtures partagées : une base PostgreSQL NEUVE par test (créée puis supprimée)."""

import os
import uuid
from collections.abc import Iterator

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
def blank_database_url() -> Iterator[str]:
    """URL d'une base vide, supprimée en fin de test (le test ne voit jamais l'URL d'origine)."""
    admin_url = _admin_url()
    name = f"foreman_t_{uuid.uuid4().hex[:16]}"
    engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool)
    with engine.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        engine.dispose()
