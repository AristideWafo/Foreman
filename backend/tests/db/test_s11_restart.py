"""S11 sur PostgreSQL avec redémarrage : le registre durable évite le doublon (étapes 1 à 4).

Le faux GitLab n'est pas durable alors qu'un vrai GitLab l'est : les MÊMES instances d'adaptateurs
traversent le redémarrage (nouvelle `App`, même base) et tiennent le rôle du fournisseur.
"""

import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from foreman.bootstrap import adapters
from foreman.bootstrap.configure import Profile, configure
from foreman.config.env import ENV_DATABASE_URL
from foreman.surfaces.web.app import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "e2e"))
from s11_run import play_round, snapshot_fakes


async def test_the_same_request_after_a_restart_reuses_the_six_resources(
    blank_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    real_build = adapters.build_adapters
    shared: dict[str, object] = {}

    def same_adapters(catalog, *, durable_registry=False):  # type: ignore[no-untyped-def]
        if not shared:
            shared.update(real_build(catalog, durable_registry=durable_registry))
        return dict(shared)

    monkeypatch.setattr(adapters, "build_adapters", same_adapters)

    first = configure(Profile.WEB)
    app = create_app(first)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        project_id = (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        project = UUID(project_id)
        one = await play_round(client, first, project)
        registry = await first.stores.registry.list_for_project(project)
        fakes = snapshot_fakes(first)
    assert len(registry) == 6

    second = configure(Profile.WEB)  # redémarrage : nouvelle App, même base, mêmes adaptateurs
    app = create_app(second)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client,
    ):
        two = await play_round(client, second, project)
        again = await second.stores.registry.list_for_project(project)
        after = snapshot_fakes(second)

    assert two.plan.plan_hash != one.plan.plan_hash and two.plan.plan_id != one.plan.plan_id
    final = [e.data for e in two.events if e.type == "card" and e.data.kind == "execution"][-1]
    assert final.state == "succeeded"
    assert len(final.resources) == 6 and all(r.reused for r in final.resources)
    key = lambda r: (r.provider, r.resource_type, r.external_id)  # noqa: E731
    assert sorted(map(key, again)) == sorted(map(key, registry))
    assert {k: v for k, v in after.items() if k != "runs"} == {
        k: v for k, v in fakes.items() if k != "runs"
    }
