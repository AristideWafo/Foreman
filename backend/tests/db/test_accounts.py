"""Comptes : invariants d'admin en concurrence, anti-élévation, migration 0006 (PostgreSQL réel)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
import sqlalchemy as sa

from foreman.core.accounts import ElevationDenied, LastAdmin, LastTeamAdmin, Team
from foreman.infra.db.accounts import PostgresAccountStore
from foreman.infra.db.engine import make_engine
from foreman.infra.db.migrate import downgrade, upgrade_head

PASSWORD_HASH = "argon2:fake"  # noqa: S105


@pytest.fixture
async def store(blank_database_url: str) -> AsyncIterator[PostgresAccountStore]:
    await asyncio.to_thread(upgrade_head, blank_database_url)
    engine = make_engine(blank_database_url)
    try:
        yield PostgresAccountStore(engine)
    finally:
        await engine.dispose()


async def outcomes(*calls: Any) -> list[object]:
    return list(await asyncio.gather(*calls, return_exceptions=True))


async def test_two_simultaneous_removals_of_the_last_admins_let_only_one_through(
    store: PostgresAccountStore,
) -> None:
    # Deux org_admin (chacun dans son équipe personnelle) se rétrogradent en même temps.
    a = await store.create_account("a@x.io", "a", PASSWORD_HASH, role="org_admin")
    b = await store.create_account("b@x.io", "b", PASSWORD_HASH, role="org_admin")
    async with store._engine.connect() as conn:
        rows = await conn.execute(sa.text("SELECT user_id, team_id FROM memberships"))
        personal = {r.user_id: r.team_id for r in rows}

    first = await outcomes(
        store.change_role(personal[a.id], a.id, "developer", actor=a.id),
        store.change_role(personal[b.id], b.id, "developer", actor=b.id),
    )
    assert sorted(type(r).__name__ for r in first) == ["LastAdmin", "NoneType"]
    assert any(isinstance(r, LastAdmin) for r in first)

    # Équipe non personnelle : deux team_admin, départs simultanés.
    c = await store.create_account("c@x.io", "c", PASSWORD_HASH)
    d = await store.create_account("d@x.io", "d", PASSWORD_HASH)
    team: Team = await store.create_team("equipe", c.id)
    await store.add_member(team.id, d.id, "team_admin", actor=c.id)
    second = await outcomes(
        store.remove_member(team.id, c.id, actor=c.id),
        store.remove_member(team.id, d.id, actor=d.id),
    )
    assert sorted(type(r).__name__ for r in second) == ["LastTeamAdmin", "NoneType"]
    assert any(isinstance(r, LastTeamAdmin) for r in second)


async def test_nobody_grants_a_role_above_their_own(store: PostgresAccountStore) -> None:
    boss = await store.create_account("boss@x.io", "boss", PASSWORD_HASH, role="org_admin")
    lead = await store.create_account("lead@x.io", "lead", PASSWORD_HASH)
    newbie = await store.create_account("new@x.io", "new", PASSWORD_HASH)
    team = await store.create_team("equipe", lead.id)
    await store.add_member(team.id, boss.id, "developer", actor=lead.id)  # égal ou inférieur : ok

    with pytest.raises(ElevationDenied):
        await store.add_member(team.id, newbie.id, "org_admin", actor=lead.id)
    with pytest.raises(ElevationDenied):
        await store.create_invitation(
            "hash-1", "x@x.io", team.id, "org_admin", lead.id, datetime(2099, 1, 1, tzinfo=UTC)
        )


def test_migration_0006_adds_then_removes_accounts_schema(blank_database_url: str) -> None:
    upgrade_head(blank_database_url)
    engine = sa.create_engine(blank_database_url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            inspector = sa.inspect(conn)
            assert {"sessions", "invitations"} <= set(inspector.get_table_names())
            assert "personal" in {c["name"] for c in inspector.get_columns("teams")}
        downgrade(blank_database_url, "0005")
        with engine.begin() as conn:
            inspector = sa.inspect(conn)
            assert not {"sessions", "invitations"} & set(inspector.get_table_names())
            assert "password_hash" not in {c["name"] for c in inspector.get_columns("users")}
    finally:
        engine.dispose()
    upgrade_head(blank_database_url)
