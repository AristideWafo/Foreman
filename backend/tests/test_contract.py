"""Contrat figé v1 : schéma des événements, forme des routes, erreurs opaques."""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from foreman.core.events import ERROR_MESSAGES, Event
from foreman.core.projects import Project
from foreman.surfaces.web.app import create_app

ADAPTER: TypeAdapter[Any] = TypeAdapter(Event)
PROJECT, TURN = str(uuid4()), str(uuid4())


def envelope(type_: str, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "seq": 1,
        "project_id": PROJECT,
        "turn_id": TURN,
        "at": datetime(2026, 10, 20, 9, 0, tzinfo=UTC).isoformat(),
        "type": type_,
        "data": data,
        **extra,
    }


EXAMPLES = {
    "message": {"role": "user", "text": "Crée Safe Eat"},
    "card": {
        "card_id": "c1",
        "kind": "plan",
        "title": "Plan de démonstration",
        "summary": "Faux agent",
        "steps": [{"step": 1, "title": "Créer le dépôt", "status": "pending"}],
    },
    "execution_step": {"card_id": "c1", "step": 1, "status": "running"},
    "turn_status": {"status": "completed"},
    "error": {"code": "internal_error", "message": ERROR_MESSAGES["internal_error"]},
}


@pytest.mark.parametrize(("type_", "data"), EXAMPLES.items())
def test_every_event_type_validates_and_roundtrips(type_: str, data: dict[str, Any]) -> None:
    source = envelope(type_, data)
    event = ADAPTER.validate_python(source)
    dumped = json.loads(ADAPTER.dump_json(event))
    assert dumped == {**source, "at": "2026-10-20T09:00:00Z"}


@pytest.mark.parametrize(
    "bad",
    [
        envelope("inconnu", {}),
        envelope("message", EXAMPLES["message"], v=2),
        envelope("message", EXAMPLES["message"], seq=0),
        envelope("message", EXAMPLES["message"], extra_field="x"),
        envelope("message", {"role": "system", "text": "x"}),
        envelope("error", {"code": "autre", "message": "x"}),
        envelope("error", {"code": "internal_error", "message": "Traceback (most recent call"}),
        envelope("message", EXAMPLES["message"], at="2026-10-20T09:00:00"),
        envelope(
            "card", {**EXAMPLES["card"], "steps": [{"step": 0, "title": "x", "status": "pending"}]}
        ),
        envelope("card", {**EXAMPLES["card"], "title": "x" * 201}),
        envelope("message", {"role": "user", "text": "x" * 8001}),
    ],
)
def test_invalid_events_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(bad)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def test_openapi_publishes_event_schema_and_routes(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    assert {ref["$ref"] for ref in schemas["Event"]["oneOf"]} == {
        f"#/components/schemas/{name}"
        for name in (
            "MessageEvent",
            "CardEvent",
            "ExecutionStepEvent",
            "TurnStatusEvent",
            "ErrorEvent",
        )
    }
    assert schemas["Event"]["discriminator"]["propertyName"] == "type"
    assert set(spec["paths"]) == {
        "/healthz",
        "/api/projects",
        "/api/projects/{project_id}",
        "/api/projects/{project_id}/messages",
        "/api/projects/{project_id}/events",
    }
    sse = spec["paths"]["/api/projects/{project_id}/events"]["get"]["responses"]["200"]
    assert "text/event-stream" in sse["content"]


def test_routes_are_declared_but_not_implemented_yet(client: TestClient) -> None:
    response = client.post("/api/projects", json={"title": "Safe Eat"})
    assert response.status_code == 501
    assert response.json() == {"error": "not_implemented"}


def test_validation_errors_are_opaque_and_never_echo_the_input(client: TestClient) -> None:
    secret = "mot-de-passe-" + "x" * 4000
    response = client.post(f"/api/projects/{uuid4()}/messages", json={"text": secret})
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert "mot-de-passe" not in response.text


def test_bad_identifier_is_an_opaque_422(client: TestClient) -> None:
    response = client.get("/api/projects/pas-un-uuid")
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_unknown_api_path_is_an_opaque_404(client: TestClient) -> None:
    response = client.get("/api/inexistant")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


def test_naive_datetimes_are_rejected_in_projects_too() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate(
            {"id": str(uuid4()), "title": "x", "created_at": "2026-10-20T09:00:00"}
        )


def test_project_creation_accepts_an_empty_body(client: TestClient) -> None:
    assert client.post("/api/projects").status_code == 501


def test_negative_after_is_rejected(client: TestClient) -> None:
    response = client.get(f"/api/projects/{uuid4()}/events?after=-1")
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_wrong_method_is_a_405_that_keeps_the_allow_header(client: TestClient) -> None:
    response = client.delete("/api/projects")
    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed"}
    assert "POST" in response.headers["allow"]


def test_unexpected_exception_is_an_opaque_500() -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret-interne postgres://user:pass@db")

    response = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {"error": "internal_error"}
    assert "secret-interne" not in response.text


def test_event_stream_documents_only_event_stream(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    ok = spec["paths"]["/api/projects/{project_id}/events"]["get"]["responses"]["200"]
    assert list(ok["content"]) == ["text/event-stream"]
    messages = spec["paths"]["/api/projects/{project_id}/messages"]["post"]["responses"]
    assert "409" in messages
