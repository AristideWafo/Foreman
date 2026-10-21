"""API `/api/admin/integrations` (#260) sur PostgreSQL réel : org_admin seul, jeton jamais rendu."""

from typing import Any

import httpx
import sqlalchemy as sa
from test_admin_api import FORBIDDEN, World, make_team, world  # noqa: F401 - `world` : fixture

from foreman.infra.db.engine import make_engine

SECRET = "ZqXkWvJmQzPwYxRtNbHs"  # noqa: S105 - valeur factice, alphabet absent des identifiants
ROUTES = [
    ("GET", "/integrations", None),
    ("PUT", "/integrations/gitlab/credentials", {"token": SECRET, "name": "read"}),
    ("DELETE", "/integrations/gitlab/credentials", None),
    ("PUT", "/integrations/anthropic/model", {"model": "claude-haiku-5-5"}),
    ("POST", "/integrations/gitlab/test", None),
]


async def test_org_admin_only_and_csrf(world: World) -> None:  # noqa: F811
    root = await world.account("root", "org_admin")
    alice, dev = await world.account("alice"), await world.account("dev")
    await make_team(await world.client(root.email), "A", alice)
    for who in (alice, dev):  # team_admin et developer : refus sur tout, rien n'est écrit
        client = await world.client(who.email)
        for method, path, body in ROUTES:
            response = await client.request(method, "/api/admin" + path, json=body)
            assert (response.status_code, response.json()) == (403, FORBIDDEN)
    no_csrf = await world.client(root.email, csrf=False)
    for method, path, body in ROUTES[1:]:  # méthodes non sûres sans jeton CSRF
        response = await no_csrf.request(method, "/api/admin" + path, json=body)
        assert (response.status_code, response.json()) == (403, FORBIDDEN)
    assert not await world.state.secrets.exists("connector.gitlab.read")


async def test_set_test_configured_never_leaks_token(world: World) -> None:  # noqa: F811
    root = await world.account("root", "org_admin")
    client = await world.client(root.email)
    seen: list[httpx.Response] = []

    async def call(method: str, path: str, body: Any = None) -> httpx.Response:
        response = await client.request(method, "/api/admin/integrations" + path, json=body)
        seen.append(response)
        assert response.headers["cache-control"] == "no-store"
        return response

    async def listing() -> dict[str, Any]:
        return {i["connector"]: i for i in (await call("GET", "")).json()}

    first = await listing()
    assert first["gitlab"]["configured"] is False and first["gitlab"]["status"] == "unprobed"
    assert {m["id"] for m in first["anthropic"]["llm"]["models"]} >= {"claude-haiku-5-5"}

    assert (await call("PUT", "/anthropic/model", {"model": "gpt-4"})).status_code == 422
    assert (await call("PUT", "/gitlab/credentials", {"token": "a b"})).status_code == 422
    for name in ("read", "write"):
        body = {"token": SECRET, "name": name}
        assert (await call("PUT", "/gitlab/credentials", body)).status_code == 204
    after_set = (await listing())["gitlab"]
    assert (after_set["configured"], after_set["status"]) == (True, "incomplete")

    tested = await call("POST", "/gitlab/test")
    assert (tested.status_code, tested.json()["status"]) == (200, "ok")
    final = (await listing())["gitlab"]
    assert final["status"] == "ok" and final["last_probe_at"]
    assert (await call("DELETE", "/gitlab/credentials")).status_code == 204
    assert not await world.state.secrets.exists("connector.gitlab.read")

    engine = make_engine(world.url)
    async with engine.connect() as conn:
        audit = (
            await conn.execute(sa.text("SELECT tool, to_jsonb(a)::text FROM audit_events a"))
        ).all()
        stored = (await conn.execute(sa.text("SELECT to_jsonb(c)::text FROM connectors c"))).all()
    await engine.dispose()
    tools = {row[0] for row in audit}
    assert {"integration.credential.set", "integration.credential.test"} <= tools
    assert "integration.credential.revoke" in tools
    haystack = " ".join(
        [r.text + str(r.headers) for r in seen] + [row[1] for row in audit] + [r[0] for r in stored]
    )
    assert not any(SECRET[i : i + 4] in haystack for i in range(len(SECRET) - 3))
