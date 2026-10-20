import asyncio
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from foreman.bootstrap.configure import App, Profile, configure, parse_dev_members
from foreman.core.clarification import answer_text
from foreman.core.events import ClarificationQuestion
from foreman.core.planning import Draft, DraftStep, Planner
from foreman.core.ports import ConversationMessage, ModelReply, Provider
from foreman.core.store import ADMIN_ROLES, DEV_USER_ID
from foreman.core.turn import TurnService
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.replay_provider import ReplayProvider
from foreman.surfaces.web.app import create_app
from support import make_planner


class GatedProvider:
    """Reste bloqué dans `complete` jusqu'à ce que le test le libère."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.started.set()
        await self.release.wait()
        return ModelReply(text="ok")


class ExplodingProvider:
    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        raise RuntimeError("secret-interne postgres://user:pass@db")


def build_app(
    provider: Provider, projects: InMemoryProjectStore | None = None
) -> tuple[FastAPI, InMemoryEventLog]:
    log = InMemoryEventLog()
    store = projects or InMemoryProjectStore()
    state = App(
        profile=Profile.WEB,
        projects=store,
        events=log,
        turns=TurnService(provider, log, make_planner(), store),
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


def test_healthz_is_a_closed_typed_object_in_openapi() -> None:
    schema = TestClient(create_app()).get("/openapi.json").json()["components"]["schemas"]
    assert set(schema["HealthResponse"]["properties"]) == {
        "status",
        "profile",
        "version",
        "persistence",
    }


def test_healthz_reports_the_version_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app())
    monkeypatch.setenv("FOREMAN_VERSION", "0.2.0")
    expected = {"status": "ok", "profile": "web", "persistence": "memory"}
    assert client.get("/healthz").json() == {**expected, "version": "0.2.0"}
    monkeypatch.setenv("FOREMAN_VERSION", "1.0 (abc)")
    assert client.get("/healthz").json() == {**expected, "version": "1.0__abc_"}
    monkeypatch.delenv("FOREMAN_VERSION")
    assert client.get("/healthz").json() == {**expected, "version": "dev"}


def test_me_is_the_dev_identity_and_a_developer_cannot_give_the_admin_approval() -> None:
    client = TestClient(create_app())
    assert client.get("/api/me").json() == {
        "user_id": str(DEV_USER_ID),
        "name": "dev",
        "role": "developer",
    }
    project = client.post("/api/projects").json()["id"]
    response = client.post(
        f"/api/projects/{project}/plans/{uuid4()}/admin-approvals",
        json={"plan_hash": "sha256:" + "a" * 64, "decision": "approved"},
    )
    assert (response.status_code, response.json()) == (403, {"error": "forbidden"})


async def test_projects_are_listed_newest_first() -> None:
    app, _ = build_app(ReplayProvider.from_dir(catalog_dir_from_env()))
    async with http(app) as client:
        for title in ("premier", "second"):
            await client.post("/api/projects", json={"title": title})
        listed = await client.get("/api/projects")
    assert [p["title"] for p in listed.json()] == ["second", "premier"]


async def test_project_lifecycle_and_a_turn_through_the_api() -> None:
    app, log = build_app(ReplayProvider.from_dir(catalog_dir_from_env()))
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
    app, _ = build_app(ReplayProvider.from_dir(catalog_dir_from_env()))
    async with http(app) as client:
        missing = f"/api/projects/{uuid4()}"
        for response in (
            await client.get(missing),
            await client.post(f"{missing}/messages", json={"text": "salut"}),
        ):
            assert response.status_code == 404
            assert response.json() == {"error": "not_found"}


async def test_message_validation_does_not_echo_the_input() -> None:
    app, _ = build_app(ReplayProvider.from_dir(catalog_dir_from_env()))
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
    app, _ = build_app(
        ReplayProvider.from_dir(catalog_dir_from_env()), InMemoryProjectStore(max_projects=1)
    )
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


class RecordingProvider:
    """Compte les appels et garde le dernier message reçu."""

    def __init__(self) -> None:
        self.calls = 0
        self.last = ""

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.calls += 1
        self.last = messages[-1].text
        return ModelReply(text="ok")


async def test_answering_a_question_is_refused_without_echo_and_starts_no_turn() -> None:
    provider, store = RecordingProvider(), InMemoryProjectStore()
    app, log = build_app(provider, store)
    secret = "valeur-hors-options"  # noqa: S105
    async with http(app) as client:
        mine = UUID((await client.post("/api/projects")).json()["id"])
        other = UUID((await client.post("/api/projects")).json()["id"])
        question = ClarificationQuestion(
            id="q1-1", field="environment", prompt="Où ?", options=["staging"], status="open"
        )
        await store.set_open_questions(mine, [question])
        url = f"/api/projects/{mine}/questions/q1-1"
        foreign = await client.post(
            f"/api/projects/{other}/questions/q1-1", json={"decision": "answer", "value": "staging"}
        )
        outside = await client.post(url, json={"decision": "answer", "value": secret})
        assert provider.calls == 0  # aucun refus n'a lancé de tour

        subscription = log.subscribe(mine)
        accepted = await client.post(url, json={"decision": "answer", "value": "staging"})
        async with asyncio.timeout(5):
            while event := await subscription.next():
                if event.type == "turn_status" and event.data.status == "completed":
                    break
        subscription.close()
        again = await client.post(url, json={"decision": "answer", "value": "staging"})

    assert (foreign.status_code, foreign.json()) == (404, {"error": "not_found"})
    assert (outside.status_code, outside.json()) == (422, {"error": "invalid_request"})
    assert secret not in outside.text
    assert (accepted.status_code, accepted.json()) == (
        202,
        {"question_id": "q1-1", "status": "answered"},
    )
    assert (again.status_code, again.json()) == (409, {"error": "question_closed"})
    assert provider.calls == 1
    assert provider.last == answer_text("environment", "staging")  # texte produit par la route
    assert [q.status for q in await store.get_open_questions(mine)] == ["answered"]


def test_proxy_header_mode_requires_a_known_identity_and_reads_the_role_from_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOREMAN_AUTH_MODE", "proxy_header")
    monkeypatch.setenv("FOREMAN_DEV_MEMBERS", "alice:developer,bob:team_admin")
    with TestClient(create_app()) as client:  # le démarrage synchronise les membres
        for headers in ({}, {"X-Forwarded-User": "mallory"}, {"X-Forwarded-User": " "}):
            response = client.get("/api/me", headers=headers)
            assert (response.status_code, response.json()) == (401, {"error": "unauthenticated"})
        assert client.get("/api/projects").status_code == 401  # toutes les routes, pas /me seul
        bob = client.get("/api/me", headers={"X-Forwarded-User": "bob"}).json()
        assert (bob["name"], bob["role"]) == ("bob", "team_admin")


def test_proxy_header_refuses_empty_members_and_duplicate_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FOREMAN_AUTH_MODE", "proxy_header")
    monkeypatch.delenv("FOREMAN_DEV_MEMBERS", raising=False)
    with pytest.raises(ValueError):
        configure(Profile.WEB)
    with pytest.raises(ValueError):
        parse_dev_members("alice:developer,alice:team_admin")


def test_none_mode_ignores_the_forwarded_user_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOREMAN_DEV_MEMBERS", "bob:org_admin")
    with TestClient(create_app()) as client:
        me = client.get("/api/me", headers={"X-Forwarded-User": "bob"}).json()
    assert me == {"user_id": str(DEV_USER_ID), "name": "dev", "role": "developer"}


def test_admin_approval_over_http_approves_then_replays_and_a_rejection_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contrat : 201 puis 200 idempotent (ApprovalAccepted) ; refus = 200 ApprovalRejected."""
    monkeypatch.setenv("FOREMAN_AUTH_MODE", "proxy_header")
    monkeypatch.setenv("FOREMAN_DEV_MEMBERS", "dev:developer,admin:team_admin")
    state = configure(Profile.WEB)
    dev = {"X-Forwarded-User": "dev"}
    admin = {"X-Forwarded-User": "admin"}

    def draft(title: str) -> Draft:
        step = DraftStep(
            "Préparer",
            "server.apply_playbook",
            {
                "environment": "production",
                "project": "safe-eat",
                "playbook": "bootstrap_project",
                "mode": "apply",
            },
        )
        return Draft(title=title, summary="s", environment="production", steps=[step])

    with TestClient(create_app(state)) as client:
        dev_id = UUID(client.get("/api/me", headers=dev).json()["user_id"])
        project = client.post("/api/projects", json={}, headers=dev).json()["id"]
        planner = Planner(state.catalog, state.stores.plans, state.stores.registry)  # type: ignore[arg-type]
        plans = [
            asyncio.run(planner.propose(UUID(project), draft(t), dev_id))[0] for t in ("a", "b")
        ]
        base = f"/api/projects/{project}/plans"
        for record in plans:
            pending = client.post(
                f"{base}/{record.id}/approvals",
                json={"plan_hash": record.content_hash, "decision": "approved"},
                headers=dev,
            )
            assert pending.status_code == 202

        body = {"plan_hash": plans[0].content_hash, "decision": "approved"}
        url = f"{base}/{plans[0].id}/admin-approvals"
        first = client.post(url, json=body, headers=admin)
        again = client.post(url, json=body, headers=admin)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json() == again.json() and "execution_id" in first.json()

        refusal = client.post(
            f"{base}/{plans[1].id}/admin-approvals",
            json={"plan_hash": plans[1].content_hash, "decision": "rejected"},
            headers=admin,
        )
        assert (refusal.status_code, refusal.json()["status"]) == (200, "rejected")
        assert "ApprovalRejected" in client.get("/openapi.json").json()["components"]["schemas"]
        stored = asyncio.run(state.stores.plans.get(UUID(project), plans[1].id))
        assert stored is not None and stored.status == "invalidated"


def test_admin_roles_in_the_store_match_the_policy_matrix() -> None:
    assert set(ADMIN_ROLES) == set(load_catalog(environment="staging").policy.approvers.admin)
