"""Mot de passe, sessions, CSRF et CLI admin (#222), de bout en bout sur PostgreSQL réel."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.bootstrap.configure import App, Profile, configure
from foreman.config.env import ENV_AUTH_MODE, ENV_COOKIE_SECURE, ENV_DATABASE_URL
from foreman.core.auth import create_admin_invitation
from foreman.core.identity import Member
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.surfaces.cli.main import _admin_create
from foreman.surfaces.web.app import create_app

EMAIL = "root@example.org"
PASSWORD = "correct horse battery"  # noqa: S105
ORIGIN = {"Origin": "http://test"}


@pytest.fixture
async def served(
    blank_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[App, httpx.AsyncClient]]:
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    monkeypatch.setenv(ENV_AUTH_MODE, "session")
    monkeypatch.setenv(ENV_COOKIE_SECURE, "0")  # le client de test parle HTTP
    state = configure(Profile.WEB)
    app = create_app(state)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield state, client


def token_of(link: str) -> str:
    return parse_qs(urlsplit(link).fragment)["token"][0]


async def activate(client: httpx.AsyncClient, token: str, email: str = EMAIL) -> httpx.Response:
    body = {"token": token, "email": email, "name": "Root", "password": PASSWORD}
    return await client.post("/api/auth/accept-invite", json=body, headers=ORIGIN)


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    body = {"email": email, "password": password}
    return await client.post("/api/auth/login", json=body, headers=ORIGIN)


async def test_admin_create_then_invite_login_me_and_logout(
    served: tuple[App, httpx.AsyncClient],
) -> None:
    app, client = served
    link = await _admin_create(EMAIL)  # chemin réel de `foreman admin create`
    assert "#token=" in link
    assert (await activate(client, token_of(link))).status_code == 204
    assert (await activate(client, token_of(link))).status_code == 422  # usage unique

    # Invitation expirée : refusée, sans dire pourquoi.
    assert app.accounts is not None and app.auth is not None
    old = datetime.now(UTC) - timedelta(hours=2)
    expired = await create_admin_invitation(app.accounts, app.auth, "late@example.org", old)
    assert (await activate(client, expired, "late@example.org")).status_code == 422

    logged = await login(client, EMAIL.upper(), PASSWORD)
    assert logged.status_code == 204
    cookie = logged.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    me = (await client.get("/api/me")).json()
    assert me["role"] == "org_admin" and len(me["csrf_token"]) == 64

    csrf = {**ORIGIN, "X-Foreman-CSRF": me["csrf_token"]}
    assert (await client.post("/api/auth/logout", headers=csrf)).status_code == 204
    assert (await client.get("/api/me")).status_code == 401


async def test_sessions_refuse_missing_csrf_unknown_users_and_brute_force(
    served: tuple[App, httpx.AsyncClient],
) -> None:
    _, client = served
    await activate(client, token_of(await _admin_create(EMAIL)))
    assert (await client.get("/api/me")).status_code == 401  # pas de cookie
    client.cookies.set("foreman_session", "forged")
    forged = await client.get("/api/me")
    assert (forged.status_code, forged.json()) == (401, {"error": "unauthenticated"})
    client.cookies.clear()

    # Même réponse pour un e-mail inconnu et un mauvais mot de passe.
    unknown = await login(client, "nobody@example.org", "whatever-password")
    wrong = await login(client, EMAIL, "whatever-password")
    assert (unknown.status_code, unknown.json()) == (wrong.status_code, wrong.json())
    assert wrong.status_code == 401

    assert (await login(client, EMAIL, PASSWORD)).status_code == 204
    csrf = (await client.get("/api/me")).json()["csrf_token"]
    post = {"title": "x"}
    assert (await client.post("/api/projects", json=post, headers=ORIGIN)).status_code == 403
    bad = {**ORIGIN, "X-Foreman-CSRF": "0" * 64}
    assert (await client.post("/api/projects", json=post, headers=bad)).status_code == 403
    foreign = {"Origin": "http://evil.example", "X-Foreman-CSRF": csrf}
    assert (await client.post("/api/projects", json=post, headers=foreign)).status_code == 403
    assert (await client.get("/api/projects")).status_code == 200  # méthode sûre : sans jeton

    # Après 5 échecs (adresse et e-mail), même le bon mot de passe est refusé (429).
    client.cookies.clear()
    for _ in range(3):  # 2 échecs plus haut + 3 = 5 pour cette adresse
        assert (await login(client, EMAIL, "whatever-password")).status_code == 401
    assert (await login(client, EMAIL, PASSWORD)).status_code == 429


async def test_seed_members_never_overwrite_a_managed_install(
    served: tuple[App, httpx.AsyncClient], blank_database_url: str
) -> None:
    app, client = served
    await activate(client, token_of(await _admin_create(EMAIL)))
    engine = make_engine(blank_database_url)
    try:
        before = await _count(engine, t.memberships)
        await app.members.sync([Member("dev2", "developer")])  # amorçage rejoué : sans effet
        assert await _count(engine, t.memberships) == before
        assert not re.search("dev2", str(await _names(engine)))
    finally:
        await engine.dispose()


async def _count(engine: AsyncEngine, table: sa.Table) -> int:
    async with engine.connect() as conn:
        return (await conn.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


async def _names(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.select(t.users.c.name))).scalars())
