"""API d'administration (#224) sur PostgreSQL réel : autorisation, parcours nominal, invariants."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from foreman.bootstrap.configure import App, Profile, configure
from foreman.config.env import ENV_AUTH_MODE, ENV_COOKIE_SECURE, ENV_DATABASE_URL
from foreman.core.accounts import Account
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.surfaces.web.app import create_app

PASSWORD = "correct horse battery"  # noqa: S105
ORIGIN = {"Origin": "http://test"}
FORBIDDEN = {"error": "forbidden"}


@dataclass
class World:
    state: App
    asgi: httpx.ASGITransport
    url: str
    password_hash: str

    async def account(self, name: str, role: Any = "team_admin") -> Account:
        assert self.state.accounts is not None
        return await self.state.accounts.create_account(
            f"{name}@example.org", name, self.password_hash, role=role
        )

    async def client(self, email: str, *, csrf: bool = True) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=self.asgi, base_url="http://test")
        body = {"email": email, "password": PASSWORD}
        assert (await client.post("/api/auth/login", json=body, headers=ORIGIN)).status_code == 204
        token = (await client.get("/api/me")).json()["csrf_token"]
        client.headers.update({**ORIGIN, **({"X-Foreman-CSRF": token} if csrf else {})})
        return client

    async def audit(self) -> list[Any]:
        engine = make_engine(self.url)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(t.audit_events.c.tool, t.audit_events.c.params_redacted).where(
                        t.audit_events.c.tool.like("identity.%")
                    )
                )
            ).all()
        await engine.dispose()
        return rows


@pytest.fixture
async def world(blank_database_url: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[World]:
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    monkeypatch.setenv(ENV_AUTH_MODE, "session")
    monkeypatch.setenv(ENV_COOKIE_SECURE, "0")
    state = configure(Profile.WEB)
    app = create_app(state)
    async with app.router.lifespan_context(app):
        yield World(
            state,
            httpx.ASGITransport(app=app),
            blank_database_url,
            await state.hasher.hash(PASSWORD),
        )


async def make_team(root: httpx.AsyncClient, name: str, admin: Account) -> UUID:
    response = await root.post(
        "/api/admin/teams", json={"name": name, "first_admin_id": str(admin.id)}
    )
    assert response.status_code == 201
    return UUID(response.json()["id"])


async def test_authorization_and_anti_elevation(world: World) -> None:
    root = await world.account("root", "org_admin")
    alice, bob, dev = (
        await world.account("alice"),
        await world.account("bob"),
        await world.account("dev"),
    )
    root_c = await world.client(root.email)
    team_a, team_b = await make_team(root_c, "A", alice), await make_team(root_c, "B", bob)
    assert (
        await root_c.put(f"/api/admin/teams/{team_a}/members/{dev.id}", json={"role": "developer"})
    ).status_code == 204

    # developer (team_admin de sa seule équipe personnelle) : 403 partout sous /admin.
    dev_c = await world.client(dev.email)
    for method, path in [("GET", "/teams"), ("GET", "/users"), ("GET", "/invitations")]:
        response = await dev_c.request(method, "/api/admin" + path)
        assert (response.status_code, response.json()) == (403, FORBIDDEN)
    invite = {"email": "x@example.org", "role": "developer", "team_id": str(team_a)}
    assert (await dev_c.post("/api/admin/invitations", json=invite)).status_code == 403

    # team_admin de A : ni org_admin, ni autre équipe, ni création d'équipe, ni déplacement.
    alice_c = await world.client(alice.email)
    denied = [
        await alice_c.post(
            "/api/admin/invitations", json={**invite, "role": "org_admin", "team_id": None}
        ),
        await alice_c.post("/api/admin/invitations", json={**invite, "team_id": str(team_b)}),
        await alice_c.put(
            f"/api/admin/teams/{team_b}/members/{dev.id}", json={"role": "developer"}
        ),
        await alice_c.delete(f"/api/admin/teams/{team_b}/members/{bob.id}"),
        await alice_c.put(
            f"/api/admin/teams/{team_a}/members/{dev.id}", json={"role": "org_admin"}
        ),
        await alice_c.post("/api/admin/teams", json={"name": "C", "first_admin_id": str(alice.id)}),
        await alice_c.post(f"/api/admin/users/{dev.id}/disable"),
        await alice_c.put(f"/api/admin/projects/{uuid4()}/team", json={"team_id": str(team_a)}),
    ]
    assert [r.status_code for r in denied[:4]] == [403] * 4
    assert [r.status_code for r in denied[5:]] == [403] * 3
    assert denied[4].status_code == 422  # org_admin n'existe pas comme rôle d'équipe
    assert {u["name"] for u in (await alice_c.get("/api/admin/users")).json()} == {"alice", "dev"}
    assert [x["name"] for x in (await alice_c.get("/api/admin/teams")).json()] == ["A"]

    # Mutation sans CSRF : refusée.
    no_csrf = await world.client(alice.email, csrf=False)
    assert (await no_csrf.post("/api/admin/invitations", json=invite)).status_code == 403
    assert await world.audit() and True


async def test_invite_accept_change_role_and_audit_without_secrets(world: World) -> None:
    root = await world.account("root", "org_admin")
    alice = await world.account("alice")
    root_c = await world.client(root.email)
    team = await make_team(root_c, "A", alice)

    body = {"email": "New@Example.org", "role": "developer", "team_id": str(team)}
    created = (await root_c.post("/api/admin/invitations", json=body)).json()
    link = created["link"]
    token = parse_qs(urlsplit(link).fragment)["token"][0]
    assert urlsplit(link).path == "/accept-invite"
    listed = (await root_c.get("/api/admin/invitations")).json()
    assert [i["id"] for i in listed] == [created["id"]] and "link" not in listed[0]

    anon = httpx.AsyncClient(transport=world.asgi, base_url="http://test")
    accept = {"token": token, "email": "new@example.org", "name": "Newbie", "password": PASSWORD}
    assert (
        await anon.post("/api/auth/accept-invite", json=accept, headers=ORIGIN)
    ).status_code == 204
    reuse = await anon.post("/api/auth/accept-invite", json=accept, headers=ORIGIN)
    assert reuse.status_code == 422  # invitation réutilisée
    new_c = await world.client("new@example.org")
    me = (await new_c.get("/api/me")).json()
    assert [(x["id"], x["role"]) for x in me["teams"]] == [(str(team), "developer")]

    alice_c = await world.client("alice@example.org")
    user_id = me["user_id"]
    assert (
        await alice_c.put(f"/api/admin/teams/{team}/members/{user_id}", json={"role": "team_admin"})
    ).status_code == 204
    # Révocation : une invitation non utilisée disparaît ; l'utilisée n'est plus révocable.
    second = (
        await root_c.post("/api/admin/invitations", json={**body, "email": "b@example.org"})
    ).json()
    assert (await root_c.delete(f"/api/admin/invitations/{second['id']}")).status_code == 204
    assert (await root_c.delete(f"/api/admin/invitations/{second['id']}")).status_code == 404
    # Désactivation : la session de l'intéressé tombe.
    assert (await root_c.post(f"/api/admin/users/{user_id}/disable")).status_code == 204
    assert (await new_c.get("/api/me")).status_code == 401

    audit = await world.audit()
    tools = [r.tool for r in audit]
    for expected in (
        "identity.team.create",
        "identity.invitation.create",
        "identity.member.change_role",
        "identity.invitation.revoke",
        "identity.account.disable",
    ):
        assert expected in tools
    change = next(r for r in audit if r.tool == "identity.member.change_role")
    assert change.params_redacted == {
        "cible": f"{team}/{user_id}",
        "ancien": "developer",
        "nouveau": "team_admin",
    }
    dump = repr(audit)
    assert token not in dump and PASSWORD not in dump and "password" not in dump


async def test_last_team_admin_cannot_be_removed(world: World) -> None:
    root = await world.account("root", "org_admin")
    alice = await world.account("alice")
    root_c = await world.client(root.email)
    team = await make_team(root_c, "A", alice)
    removal = await root_c.delete(f"/api/admin/teams/{team}/members/{alice.id}")
    assert (removal.status_code, removal.json()) == (409, {"error": "last_team_admin"})
    demotion = await root_c.put(
        f"/api/admin/teams/{team}/members/{alice.id}", json={"role": "developer"}
    )
    assert (demotion.status_code, demotion.json()) == (409, {"error": "last_team_admin"})
