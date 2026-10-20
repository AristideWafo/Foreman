"""Cloisonnement par équipe (#223) sur PostgreSQL réel : un projet n'existe que pour son équipe.

Accès refusé = 404 identique à « projet inconnu » (jamais 403) sur toutes les routes du projet, flux
SSE compris ; validation sans équipe par l'inviteur (`invited_by`) avec repli.
"""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

import foreman.surfaces.web.api as api_module
from foreman.bootstrap.configure import App, Profile, configure
from foreman.config.env import ENV_AUTH_MODE, ENV_COOKIE_SECURE, ENV_DATABASE_URL
from foreman.core.accounts import Account, PersonalTeam
from foreman.core.planning import Draft, DraftStep, Planner
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.surfaces.web.app import create_app

PASSWORD = "correct horse battery"  # noqa: S105
ORIGIN = {"Origin": "http://test"}
NOT_FOUND = {"error": "not_found"}
PRODUCTION_PLAN = Draft(
    title="Groupe",
    summary="Un groupe",
    environment="production",
    steps=[
        DraftStep(
            "Racine", "gitlab.create_group", {"parent_group_id": 1000, "name": "A", "path": "aa"}
        )
    ],
)
STAGING_PLAN = Draft(
    title="Groupe",
    summary="Un groupe",
    environment="staging",
    steps=PRODUCTION_PLAN.steps,
)


@dataclass
class World:
    state: App
    asgi: httpx.ASGITransport
    url: str
    password_hash: str

    async def account(
        self, name: str, *, invited_by: UUID | None = None, role: Any = "team_admin"
    ) -> Account:
        assert self.state.accounts is not None
        return await self.state.accounts.create_account(
            f"{name}@example.org", name, self.password_hash, invited_by=invited_by, role=role
        )

    async def team(self, name: str, admin: Account) -> UUID:
        assert self.state.accounts is not None
        return (await self.state.accounts.create_team(name, admin.id)).id

    async def disable(self, account: Account) -> None:
        engine = make_engine(self.url)
        async with engine.begin() as conn:
            await conn.execute(
                sa.update(t.users)
                .where(t.users.c.id == account.id)
                .values(disabled_at=sa.func.now())
            )
        await engine.dispose()

    async def client(self, account: Account) -> httpx.AsyncClient:
        """Client connecté ; l'en-tête CSRF et l'origine sont posés pour les méthodes non sûres."""
        client = httpx.AsyncClient(transport=self.asgi, base_url="http://test")
        body = {"email": account.email, "password": PASSWORD}
        assert (await client.post("/api/auth/login", json=body, headers=ORIGIN)).status_code == 204
        csrf = (await client.get("/api/me")).json()["csrf_token"]
        client.headers.update({**ORIGIN, "X-Foreman-CSRF": csrf})
        return client

    async def project(self, client: httpx.AsyncClient, team: UUID | None = None) -> UUID:
        body = {"title": "p", **({"team_id": str(team)} if team else {})}
        response = await client.post("/api/projects", json=body)
        assert response.status_code == 201
        return UUID(response.json()["id"])

    async def plan(
        self, project: UUID, requester: Account, draft: Draft = PRODUCTION_PLAN
    ) -> tuple[UUID, str]:
        assert self.state.catalog is not None
        planner = Planner(self.state.catalog, self.state.stores.plans, self.state.stores.registry)
        record, _ = await planner.propose(project, draft, requester.id)
        return record.id, record.content_hash


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


async def test_a_project_is_invisible_to_other_teams_on_every_route(world: World) -> None:
    root = await world.account("root", role="org_admin")
    alice, bob = await world.account("alice"), await world.account("bob")
    team_a, team_b = await world.team("A", alice), await world.team("B", bob)
    a_client, b_client = await world.client(alice), await world.client(bob)
    root_client = await world.client(root)
    project_a = await world.project(a_client, team_a)
    project_b = await world.project(b_client, team_b)
    plan_b, plan_hash = await world.plan(project_b, bob)

    # Toutes les routes `/projects/{id}/...` de l'OpenAPI, sans en oublier : 404 identique à un
    # projet inconnu, quelle que soit la méthode (le corps n'est même pas lu).
    spec = (await a_client.get("/openapi.json")).json()
    routes = [
        (method, path)
        for path, item in spec["paths"].items()
        if path.startswith("/api/projects/{project_id}")  # /admin/ a sa propre autorisation
        for method in item
    ]
    assert len(routes) >= 8

    async def call(method: str, path: str, project: UUID) -> httpx.Response:
        url = path.replace("{project_id}", str(project))
        for name in ("plan_id", "execution_id", "question_id"):
            url = url.replace("{" + name + "}", str(plan_b))
        return await a_client.request(method.upper(), url, json={"plan_hash": plan_hash})

    for method, path in routes:
        foreign = await call(method, path, project_b)
        unknown = await call(method, path, uuid4())
        assert (foreign.status_code, foreign.json()) == (404, NOT_FOUND), (method, path)
        assert (foreign.status_code, foreign.json()) == (unknown.status_code, unknown.json())

    # Contrôle de non-trivialité : les propriétaires, eux, accèdent à leur projet.
    assert (await b_client.get(f"/api/projects/{project_b}")).status_code == 200
    assert (await a_client.get(f"/api/projects/{project_a}")).status_code == 200

    # Liste : chacun ne voit que ses équipes ; l'org_admin voit tout.
    listed = {p["id"] for p in (await a_client.get("/api/projects")).json()}
    assert project_a in map(UUID, listed) and project_b not in map(UUID, listed)
    seen = {UUID(p["id"]) for p in (await root_client.get("/api/projects")).json()}
    assert {project_a, project_b} <= seen
    assert (await root_client.get(f"/api/projects/{project_b}")).status_code == 200

    # Création dans l'équipe d'un autre : même 404 ; le team_admin de A n'a rien approuvé en B.
    refused = await a_client.post("/api/projects", json={"team_id": str(team_b)})
    assert (refused.status_code, refused.json()) == (404, NOT_FOUND)
    plan = await world.state.stores.plans.get(project_b, plan_b)
    assert plan is not None and plan.status == "proposed"


async def test_an_open_stream_closes_when_access_is_lost(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "ACCESS_RECHECK_SECONDS", 0.05)
    alice, dave = await world.account("alice"), await world.account("dave")
    team = await world.team("A", alice)
    assert world.state.accounts is not None
    await world.state.accounts.add_member(team, dave.id, "developer", alice.id)
    owner, member = await world.client(alice), await world.client(dave)
    project = await world.project(owner, team)

    stream = asyncio.create_task(member.get(f"/api/projects/{project}/events"))
    await world.state.events.wait_for_subscriber_count(project, 1)  # type: ignore[attr-defined]
    await world.state.accounts.remove_member(team, dave.id, alice.id)
    response = await asyncio.wait_for(stream, timeout=5)  # ne se termine que si le flux se ferme
    assert response.status_code == 200
    assert (await member.get(f"/api/projects/{project}/events")).status_code == 404


async def test_a_personal_plan_is_validated_by_the_inviter_with_fallbacks(world: World) -> None:
    root = await world.account("root", role="org_admin")
    ops1 = await world.account("ops1", invited_by=root.id)
    ops2 = await world.account("ops2", invited_by=ops1.id)
    await world.team("Ops1", ops1)
    await world.team("Ops2", ops2)
    user = await world.account("user", invited_by=ops2.id)
    stranger = await world.account("stranger")
    await world.team("Other", stranger)
    members = world.state.members
    personal = await members.personal_team_of(user.id)
    assert personal is not None

    # Inviteur actif et admin : il voit le projet et valide en admin, rien d'autre (404 opaque) ;
    # un autre team_admin n'a aucun accès ; on ne rejoint jamais une équipe personnelle.
    assert world.state.accounts is not None
    with pytest.raises(PersonalTeam):
        await world.state.accounts.add_member(personal, stranger.id, "developer", user.id)
    user_client = await world.client(user)
    ops_client, stranger_client = await world.client(ops2), await world.client(stranger)
    first = await world.project(user_client)
    first_plan, first_hash = await world.plan(first, user)
    body = {"plan_hash": first_hash, "decision": "approved"}
    base = f"/api/projects/{first}"
    own = await user_client.post(f"{base}/plans/{first_plan}/approvals", json=body)
    assert (own.status_code, own.json()) == (403, {"error": "forbidden"})  # pas le propriétaire
    assert (await ops_client.get(base)).status_code == 200
    assert (await stranger_client.get(base)).status_code == 404
    assert (
        await ops_client.post(f"{base}/plans/{first_plan}/approvals", json=body)
    ).status_code == 202  # l'approbateur désigné valide les deux étapes
    assert (
        await stranger_client.post(f"{base}/plans/{first_plan}/approvals", json=body)
    ).status_code == 404
    for path, payload in (
        (f"{base}/messages", {"text": "x"}),
        (f"{base}/questions/q1", {"decision": "answer", "value": "x"}),
    ):
        refused = await ops_client.post(path, json=payload)
        assert (refused.status_code, refused.json()) == (404, NOT_FOUND), path
    admin_path = f"{base}/plans/{first_plan}/admin-approvals"
    assert (await stranger_client.post(admin_path, json=body)).status_code == 404
    assert (await ops_client.post(admin_path, json=body)).status_code == 201

    # L'inviteur direct (admin d'une équipe non personnelle) ; puis l'ancêtre actif ; sans inviteur
    # admin, repli sur tout org_admin (ensemble vide).
    assert await members.designated_admins(personal) == {ops2.id}
    await world.disable(ops2)
    assert await members.designated_admins(personal) == {ops1.id}
    await world.disable(ops1)
    assert await members.designated_admins(personal) == {root.id}
    loner = await members.personal_team_of(stranger.id)
    assert loner is not None and await members.designated_admins(loner) == frozenset()
    assert await members.designated_admins(uuid4()) is None  # pas une équipe personnelle

    # Bout en bout : l'utilisateur ne valide jamais son propre plan ; seul l'inviteur le peut.
    project = await world.project(user_client)
    plan_id, plan_hash = await world.plan(project, user)
    body = {"plan_hash": plan_hash, "decision": "approved"}
    base = f"/api/projects/{project}/plans/{plan_id}"
    root_client = await world.client(root)
    refused_own = await user_client.post(f"{base}/approvals", json=body)
    assert (refused_own.status_code, refused_own.json()) == (403, {"error": "forbidden"})
    assert (await root_client.post(f"{base}/approvals", json=body)).status_code == 202
    own = await user_client.post(f"{base}/admin-approvals", json=body)
    assert (own.status_code, own.json()) == (403, {"error": "forbidden"})
    other = await (await world.client(stranger)).post(f"{base}/admin-approvals", json=body)
    assert (other.status_code, other.json()) == (404, NOT_FOUND)  # pas même d'accès au projet
    # Les deux premiers inviteurs sont désactivés : l'ancêtre org_admin valide.
    assert (await root_client.post(f"{base}/admin-approvals", json=body)).status_code == 201


async def test_an_org_admin_may_validate_their_own_plan_but_it_is_audited(world: World) -> None:
    root = await world.account("root", role="org_admin")
    client = await world.client(root)
    project = await world.project(client)
    plan_id, plan_hash = await world.plan(project, root)
    body = {"plan_hash": plan_hash, "decision": "approved"}
    base = f"/api/projects/{project}/plans/{plan_id}"
    assert (await client.post(f"{base}/approvals", json=body)).status_code == 202
    assert (await client.post(f"{base}/admin-approvals", json=body)).status_code == 201
    entries = await world.state.stores.audit.list_for_project(project)
    assert [e.decision for e in entries if e.tool == "plan.approve_admin"] == ["auto-validation"]


async def test_a_developer_cannot_validate_their_own_personal_plan_even_in_staging(
    world: World,
) -> None:
    """Régression #248 : en session, tout compte est team_admin de son équipe personnelle ; un
    `developer` d'une équipe partagée y validait son plan, et en staging l'exécution partait."""
    ops = await world.account("ops")
    shared = await world.team("Shared", ops)
    dev = await world.account("dev", invited_by=ops.id)
    assert world.state.accounts is not None
    await world.state.accounts.add_member(shared, dev.id, "developer", ops.id)
    dev_client, ops_client = await world.client(dev), await world.client(ops)
    project = await world.project(dev_client)  # équipe personnelle par défaut
    plan_id, plan_hash = await world.plan(project, dev, STAGING_PLAN)
    body = {"plan_hash": plan_hash, "decision": "approved"}
    url = f"/api/projects/{project}/plans/{plan_id}/approvals"

    refused = await dev_client.post(url, json=body)
    assert (refused.status_code, refused.json()) == (403, {"error": "forbidden"})
    plan = await world.state.stores.plans.get(project, plan_id)
    assert plan is not None and plan.status == "proposed"
    assert await world.state.stores.executions.list_resumable() == []
    assert (await dev_client.get(f"/api/projects/{project}")).json()["can_approve"] is False

    assert (await ops_client.get(f"/api/projects/{project}")).json()["can_approve"] is True
    assert (await ops_client.post(url, json=body)).status_code == 201  # l'inviteur admin valide
