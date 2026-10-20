"""Choix de l'adaptateur au démarrage, migrations dans le `lifespan`, survie au redémarrage."""

import asyncio
import logging

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI

from foreman.bootstrap.configure import Profile, configure
from foreman.bootstrap.database import DatabaseLifecycle
from foreman.config.env import ENV_DATABASE_URL
from foreman.core.identity import Member
from foreman.core.store import DEV_TEAM_ID
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.infra.db.members import PostgresMemberStore
from foreman.infra.db.migrate import upgrade_head
from foreman.infra.db.projects import PostgresProjectStore, seed_dev_identity
from foreman.infra.in_memory import InMemoryProjectStore
from foreman.surfaces.web.app import create_app

UNREACHABLE = "postgresql+psycopg://foreman:TOP-SECRET-PW@127.0.0.1:1/foreman"


def http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_postgres_is_chosen_only_when_the_url_is_set_for_a_persistent_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_DATABASE_URL, raising=False)
    assert isinstance(configure(Profile.WEB).projects, InMemoryProjectStore)
    monkeypatch.setenv(ENV_DATABASE_URL, UNREACHABLE)  # aucune connexion à la construction
    assert isinstance(configure(Profile.WEB).projects, PostgresProjectStore)
    assert isinstance(configure(Profile.CLI).projects, InMemoryProjectStore)


async def test_a_project_created_in_postgres_survives_a_restart(
    blank_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    first = create_app()
    async with first.router.lifespan_context(first), http(first) as client:
        created = await client.post("/api/projects", json={"title": "Safe Eat"})
        assert created.status_code == 201
        project_id = created.json()["id"]

    second = create_app()  # nouveau processus : migrations rejouées sans effet, amorçage idempotent
    async with second.router.lifespan_context(second), http(second) as client:
        found = await client.get(f"/api/projects/{project_id}")
        assert found.status_code == 200
        assert found.json()["title"] == "Safe Eat"


async def test_two_applications_starting_together_migrate_and_seed_once(
    blank_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    apps = [create_app(), create_app()]

    async def run(app: FastAPI) -> None:
        async with app.router.lifespan_context(app):
            return None

    await asyncio.wait_for(asyncio.gather(*(run(app) for app in apps)), timeout=60)
    engine = make_engine(blank_database_url)
    try:
        async with engine.connect() as conn:
            users = (await conn.execute(sa.select(sa.func.count()).select_from(t.users))).scalar()
            teams = (await conn.execute(sa.select(sa.func.count()).select_from(t.teams))).scalar()
    finally:
        await engine.dispose()
    assert (users, teams) == (1, 1)


async def test_an_unreachable_database_fails_the_startup_without_leaking_its_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = make_engine(UNREACHABLE)
    lifecycle = DatabaseLifecycle(UNREACHABLE, engine, attempts=2, delay_s=0)
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as failure:
        await lifecycle.start()
    await lifecycle.stop()
    everything = caplog.text + str(failure.value) + repr(failure.value.__cause__)
    assert "TOP-SECRET-PW" not in everything
    assert "foreman:" not in everything
    assert caplog.text.count("tentative") == 2  # reconnexions bornées


async def test_member_sync_replaces_roles_and_keeps_the_users(blank_database_url: str) -> None:
    engine = make_engine(blank_database_url)
    await asyncio.to_thread(upgrade_head, blank_database_url)
    await seed_dev_identity(engine)
    members = PostgresMemberStore(engine)
    alice, bob = Member("alice", "developer"), Member("bob", "team_admin")
    await members.sync([alice, bob])
    assert await members.role_in(bob.user_id, DEV_TEAM_ID) == "team_admin"
    await members.sync([alice])  # bob retiré du .env : il perd son rôle
    assert await members.role_in(bob.user_id, DEV_TEAM_ID) is None
    assert await members.role_in(alice.user_id, DEV_TEAM_ID) == "developer"
    async with engine.connect() as conn:
        count = await conn.execute(sa.select(sa.func.count()).select_from(t.users))
        assert count.scalar() == 3  # dev, alice, bob : les utilisateurs ne sont jamais supprimés
    await engine.dispose()
