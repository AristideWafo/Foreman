import asyncio
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foreman.bootstrap.configure import App, Profile
from foreman.core.ports import ModelReply, Provider
from foreman.core.turn import TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.scripted_provider import ScriptedProvider
from foreman.surfaces.web.app import create_app


class GatedProvider:
    """Reste bloqué dans `complete` jusqu'à ce que le test le libère."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        self.started.set()
        await self.release.wait()
        return ModelReply(text="ok")


class ExplodingProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        raise RuntimeError("secret-interne postgres://user:pass@db")


def build_app(
    provider: Provider, projects: InMemoryProjectStore | None = None
) -> tuple[FastAPI, InMemoryEventLog]:
    log = InMemoryEventLog()
    state = App(
        profile=Profile.WEB,
        projects=projects or InMemoryProjectStore(),
        events=log,
        turns=TurnService(provider, log),
    )
    return create_app(state), log


def http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def wait_for_status(log: InMemoryEventLog, project_id: UUID, status: str) -> None:
    subscription = log.subscribe(project_id)
    try:
        async with asyncio.timeout(5):
            while (event := await subscription.next()) is not None:
                if event.type == "turn_status" and event.data.status == status:
                    return
    finally:
        subscription.close()
    raise AssertionError("flux fermé avant le statut attendu")


def test_healthz() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "profile": "web"}


async def test_project_lifecycle_and_a_turn_through_the_api() -> None:
    app, log = build_app(ScriptedProvider())
    async with http(app) as client:
        created = await client.post("/api/projects", json={"title": "Safe Eat"})
        assert created.status_code == 201
        project = created.json()
        assert project["title"] == "Safe Eat"
        assert (await client.get(f"/api/projects/{project['id']}")).json() == project

        subscription = log.subscribe(UUID(project["id"]))
        accepted = await client.post(
            f"/api/projects/{project['id']}/messages", json={"text": "Crée Safe Eat"}
        )
        assert accepted.status_code == 202
        turn_id = accepted.json()["turn_id"]
        seen: list[str] = []
        async with asyncio.timeout(5):
            while event := await subscription.next():
                seen.append(event.type)
                assert str(event.turn_id) == turn_id
                if event.type == "turn_status" and event.data.status == "completed":
                    break
    assert seen == ["message", "turn_status", "message", "card", "turn_status"]


async def test_unknown_project_is_an_opaque_404() -> None:
    app, _ = build_app(ScriptedProvider())
    async with http(app) as client:
        missing = f"/api/projects/{uuid4()}"
        for response in (
            await client.get(missing),
            await client.post(f"{missing}/messages", json={"text": "salut"}),
        ):
            assert response.status_code == 404
            assert response.json() == {"error": "not_found"}


async def test_message_validation_does_not_echo_the_input() -> None:
    app, _ = build_app(ScriptedProvider())
    async with http(app) as client:
        project = (await client.post("/api/projects")).json()
        secret = "mot-de-passe-" + "x" * 4000
        response = await client.post(
            f"/api/projects/{project['id']}/messages", json={"text": secret}
        )
    assert response.status_code == 422
    assert "mot-de-passe" not in response.text


async def test_second_message_during_a_turn_is_a_409_and_the_turn_is_not_duplicated() -> None:
    provider = GatedProvider()
    app, log = build_app(provider)
    async with http(app) as client:
        project_id = (await client.post("/api/projects")).json()["id"]
        url = f"/api/projects/{project_id}/messages"
        assert (await client.post(url, json={"text": "un"})).status_code == 202
        await asyncio.wait_for(provider.started.wait(), timeout=5)

        concurrent = await client.post(url, json={"text": "deux"})
        assert concurrent.status_code == 409
        assert concurrent.json() == {"error": "turn_in_progress"}

        provider.release.set()
        await wait_for_status(log, UUID(project_id), "completed")
        assert (await client.post(url, json={"text": "trois"})).status_code == 202
    events = await log.read_after(UUID(project_id), 0)
    texts = [e.data.text for e in events if e.type == "message" and e.data.role == "user"]
    assert "deux" not in texts


async def test_provider_failure_through_the_api_leaks_nothing() -> None:
    app, log = build_app(ExplodingProvider())
    async with http(app) as client:
        project_id = (await client.post("/api/projects")).json()["id"]
        subscription = log.subscribe(UUID(project_id))
        response = await client.post(
            f"/api/projects/{project_id}/messages", json={"text": "texte-utilisateur"}
        )
        assert response.status_code == 202
        events = []
        async with asyncio.timeout(5):
            while event := await subscription.next():
                events.append(event)
                if event.type == "turn_status" and event.data.status == "failed":
                    break
    failure = [e.model_dump_json() for e in events if e.type in {"error", "turn_status"}]
    assert any('"internal_error"' in f for f in failure)
    assert all("secret-interne" not in f and "texte-utilisateur" not in f for f in failure)


async def test_project_cap_is_a_503() -> None:
    app, _ = build_app(ScriptedProvider(), InMemoryProjectStore(max_projects=1))
    async with http(app) as client:
        assert (await client.post("/api/projects")).status_code == 201
        full = await client.post("/api/projects")
    assert full.status_code == 503
    assert full.json() == {"error": "capacity_exceeded"}


# --- Repli SPA -----------------------------------------------------------------------------


@pytest.fixture
def spa(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "index.html").write_text("<h1>spa</h1>")
    (tmp_path / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("FOREMAN_STATIC_DIR", str(tmp_path))
    return TestClient(create_app())


def test_serves_spa_and_static_files_when_static_dir_is_set(spa: TestClient) -> None:
    assert spa.get("/").text == "<h1>spa</h1>"
    assert spa.get("/app.js").text == "console.log(1)"
    assert spa.get("/healthz").json()["status"] == "ok"


def test_deep_link_serves_the_spa(spa: TestClient) -> None:
    response = spa.get("/projects/abc")
    assert response.status_code == 200
    assert response.text == "<h1>spa</h1>"


def test_unknown_api_path_stays_an_opaque_json_404_with_the_spa(spa: TestClient) -> None:
    response = spa.get("/api/inexistant")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_missing_static_file_is_a_404_not_the_spa(spa: TestClient) -> None:
    assert spa.get("/assets/absent.js").status_code == 404


def test_no_spa_fallback_without_a_static_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_STATIC_DIR", raising=False)
    assert TestClient(create_app()).get("/projects/abc").status_code == 404


def test_unknown_api_path_is_a_404_for_every_method_even_with_the_spa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "index.html").write_text("<h1>spa</h1>")
    monkeypatch.setenv("FOREMAN_STATIC_DIR", str(tmp_path))
    client = TestClient(create_app())
    for method in ("GET", "POST", "DELETE"):
        response = client.request(method, "/api/inexistant")
        assert response.status_code == 404, method
        assert response.json() == {"error": "not_found"}, method
