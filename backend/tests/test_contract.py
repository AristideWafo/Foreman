"""Contrat figé v1 : schéma des événements, forme des routes, erreurs opaques."""

import json
from datetime import UTC, datetime
from typing import Any, get_args
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from foreman.core.events import ERROR_MESSAGES, Event, PlanStatus
from foreman.core.projects import Project
from foreman.surfaces.web.app import create_app
from foreman.surfaces.web.schemas import PlanView

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


SHA = "sha256:" + "a" * 64
STEP_META = {
    "tool": "gitlab.create_group",
    "tool_class": "write_registry",
    "reversibility": "compensable",
}

# Format de la Semaine 1 : doit rester valide tel quel (les ajouts sont facultatifs).
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


NEW_EXAMPLES = {
    "card (plan complet, Semaine 2)": (
        "card",
        {
            **EXAMPLES["card"],
            "steps": [{"step": 1, "title": "Groupe", "status": "pending", **STEP_META}],
            "plan_id": str(uuid4()),
            "plan_hash": SHA,
            "status": "proposed",
            "environment": "staging",
            "autonomy_level": 2,
            "stack": {"backend": "go", "frontend": "react"},
            "skills": [{"name": "gitlab-project-creation", "version": 1, "sha256": SHA}],
            "expected_resources": [
                {"provider": "gitlab", "resource_type": "group", "name": "safe-eat"}
            ],
            "approvable": True,
        },
    ),
    "card (plan invalidé, Semaine 6)": (
        "card",
        {
            **EXAMPLES["card"],
            "plan_id": str(uuid4()),
            "plan_hash": SHA,
            "status": "invalidated",
            "invalidation": {
                "reason": "catalog_changed",
                "changes": [{"kind": "skill", "name": "gitlab-project-creation"}],
            },
        },
    ),
    "card (exécution)": (
        "card",
        {
            "card_id": "exec-1",
            "kind": "execution",
            "execution_id": str(uuid4()),
            "plan_card_id": "c1",
            "state": "running",
            "autonomy_level": 2,
            "steps": [{"step": 1, "title": "Groupe", "status": "running", **STEP_META}],
            "budget": {
                "tool_calls_used": 1,
                "tool_calls_max": 60,
                "elapsed_s": 3,
                "max_minutes": 30,
            },
            "resources": [
                {
                    "provider": "gitlab",
                    "resource_type": "group",
                    "name": "safe-eat",
                    "url": "https://gitlab.example.org/safe-eat",
                    "reused": True,
                }
            ],
            "result": {
                "summary": "Projet créé",
                "links": [{"label": "GitLab", "url": "https://gitlab.example.org/safe-eat"}],
            },
        },
    ),
    "execution_log": (
        "execution_log",
        {"card_id": "exec-1", "step": 7, "lines": ["TASK [compose up] changed"]},
    ),
    "error (plan invalide)": (
        "error",
        {"code": "invalid_plan", "message": ERROR_MESSAGES["invalid_plan"]},
    ),
}


def assert_same_but_nulls(source: Any, dumped: Any) -> None:
    """Le serveur sérialise aussi les champs vides (`null`) : seuls des `null` peuvent s'ajouter."""
    if isinstance(source, dict):
        assert isinstance(dumped, dict)
        for key, value in dumped.items():
            if key in source:
                assert_same_but_nulls(source[key], value)
            else:
                assert value is None or value == [], key
    elif isinstance(source, list):
        assert len(source) == len(dumped)
        for a, b in zip(source, dumped, strict=True):
            assert_same_but_nulls(a, b)
    else:
        assert source == dumped


@pytest.mark.parametrize(
    ("type_", "data"),
    [*EXAMPLES.items(), *NEW_EXAMPLES.values()],
    ids=[*EXAMPLES, *NEW_EXAMPLES],
)
def test_every_event_type_validates_and_roundtrips(type_: str, data: dict[str, Any]) -> None:
    source = envelope(type_, data)
    event = ADAPTER.validate_python(source)
    dumped = json.loads(ADAPTER.dump_json(event))
    assert_same_but_nulls({**source, "at": "2026-10-20T09:00:00Z"}, dumped)


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
        envelope("card", {**EXAMPLES["card"], "kind": "tableau"}),  # kind inconnu
        envelope("card", {**EXAMPLES["card"], "plan_hash": "sha256:court"}),
        envelope("card", {**EXAMPLES["card"], "champ_inconnu": 1}),
        envelope("card", {**NEW_EXAMPLES["card (exécution)"][1], "state": "inconnu"}),
        envelope(
            "card",
            {
                **NEW_EXAMPLES["card (exécution)"][1],
                "result": {
                    "summary": "x",
                    "links": [{"label": "piège", "url": "javascript:alert(1)"}],
                },
            },
        ),
        envelope("execution_log", {"card_id": "c", "step": 1, "lines": ["x"] * 51}),
        envelope("execution_log", {"card_id": "c", "step": 1, "lines": ["x" * 501]}),
        envelope("error", {"code": "invalid_plan", "message": "Traceback (most recent call"}),
        envelope("message", {"role": "user", "text": "x" * 8001}),
        envelope("card", {**EXAMPLES["card"], "status": "approved"}),  # hors des 6 états du plan
        envelope("card", {**EXAMPLES["card"], "stack": {"__proto__": "x"}}),
        envelope("card", {**EXAMPLES["card"], "stack": {"python": "x" * 101}}),
        envelope("card", {**EXAMPLES["card"], "stack": {f"k{i}": "v" for i in range(11)}}),
        *(
            envelope(
                "card",
                {
                    **NEW_EXAMPLES["card (exécution)"][1],
                    "result": {"summary": "x", "links": [{"label": "l", "url": url}]},
                },
            )
            for url in (
                "http://exemple.test/x\nhttps://y",
                "https://x\njavascript:1",
                "https://x\x00",
                "ftp://exemple.test",
            )
        ),
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
            "ExecutionLogEvent",
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
        "/api/projects/{project_id}/plans/{plan_id}",
        "/api/projects/{project_id}/plans/{plan_id}/approvals",
        "/api/projects/{project_id}/plans/{plan_id}/admin-approvals",
        "/api/me",
        "/api/projects/{project_id}/executions/{execution_id}",
        "/api/projects/{project_id}/questions/{question_id}",
    }
    card = schemas["CardEvent"]["properties"]["data"]
    assert card["discriminator"]["propertyName"] == "kind"
    assert set(card["discriminator"]["mapping"]) == {
        "plan",
        "execution",
        "clarification",
        "approval",
    }
    assert (
        "kind" in schemas["PlanCardData"]["required"]
    )  # discriminant requis dans le schéma publié
    assert "kind" in schemas["ExecutionCardData"]["required"]
    sse = spec["paths"]["/api/projects/{project_id}/events"]["get"]["responses"]["200"]
    assert "text/event-stream" in sse["content"]


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
    response = client.post("/api/projects")
    assert response.status_code == 201
    assert response.json()["title"] == ""


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


PLAN, OTHER = uuid4(), uuid4()


def test_unknown_plans_and_executions_are_opaque_404s(client: TestClient) -> None:
    body = {"plan_hash": SHA, "decision": "approved"}
    for response in (
        client.post(f"/api/projects/{OTHER}/plans/{PLAN}/approvals", json=body),
        client.get(f"/api/projects/{OTHER}/plans/{PLAN}"),
        client.get(f"/api/projects/{OTHER}/executions/{PLAN}"),
    ):
        assert (response.status_code, response.json()) == (404, {"error": "not_found"})


@pytest.mark.parametrize(
    "body",
    [
        {"plan_hash": "sha256:court", "decision": "approved"},
        {"plan_hash": SHA, "decision": "rejected"},  # S1 : seule l'approbation existe
        {"plan_hash": SHA},
        {"decision": "approved"},
        {"plan_hash": SHA, "decision": "approved", "en_trop": 1},
    ],
)
def test_approval_body_is_validated_and_the_422_is_opaque(
    client: TestClient, body: dict[str, Any]
) -> None:
    response = client.post(f"/api/projects/{OTHER}/plans/{PLAN}/approvals", json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_approval_conflicts_are_documented_with_their_codes(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/projects/{project_id}/plans/{plan_id}/approvals"]["post"][
        "responses"
    ]
    assert "409" in responses
    for code in ("plan_hash_mismatch", "plan_not_approvable", "execution_in_progress"):
        assert code in responses["409"]["description"]
        assert code in spec["components"]["schemas"]["ErrorResponse"]["properties"]["error"]["enum"]


def test_plan_view_and_plan_card_share_one_status_vocabulary() -> None:
    card = get_args(PlanStatus)
    view = get_args(PlanView.model_fields["status"].annotation)
    assert (
        set(card)
        == set(view)
        == {
            "proposed",
            "dev_approved",
            "admin_approved",
            "invalidated",
            "expired",
            "executed",
        }
    )


def test_approval_documents_created_and_idempotent_replay(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/projects/{project_id}/plans/{plan_id}/approvals"]["post"][
        "responses"
    ]
    assert {"200", "201", "404", "409"} <= set(responses)


# Champs requis des types figés en S1 : un ajout se fait en optionnel (v1) ; si ce test échoue
# parce qu'un champ est devenu requis, c'est un changement non additif => contrat v2.
FROZEN_REQUIRED = {
    "MessageData": {"role", "text"},
    "CardStep": {"step", "title", "status"},
    "PlanCardData": {"card_id", "kind", "title", "summary", "steps"},
    "ExecutionStepData": {"card_id", "step", "status"},
    "ErrorData": {"code", "message"},
}


@pytest.mark.parametrize("name", sorted(FROZEN_REQUIRED))
def test_s1_required_fields_stay_frozen(client: TestClient, name: str) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"].get(name)
    assert schema is not None, f"{name} supprimé ou renommé => contrat v2"
    assert set(schema.get("required", [])) == FROZEN_REQUIRED[name]


@pytest.mark.parametrize("label", sorted(NEW_EXAMPLES))
def test_examples_cover_every_field_of_their_model(label: str) -> None:
    # Un champ ajouté au modèle sans exemple ne serait ni validé ni rejoué : il doit y figurer.
    type_, data = NEW_EXAMPLES[label]
    event = ADAPTER.validate_python(envelope(type_, data))
    dumped = json.loads(event.data.model_dump_json())
    assert set(dumped) == set(type(event.data).model_fields)
    assert set(data) <= set(dumped)


def test_clarification_card_rejects_out_of_bounds_input() -> None:
    question = {
        "id": "q1",
        "field": "environment",
        "prompt": "Quel environnement ?",
        "status": "open",
    }
    card = {"card_id": "c", "kind": "clarification", "questions": [question]}
    ADAPTER.validate_python(envelope("card", card))  # forme valide
    for bad in (
        {**card, "questions": [question] * 6},
        {**card, "questions": [{**question, "options": ["a"] * 11}]},
        {**card, "questions": [{**question, "prompt": "x" * 301}]},
        {**card, "questions": [{**question, "inconnu": 1}]},
    ):
        with pytest.raises(ValidationError):
            ADAPTER.validate_python(envelope("card", bad))


def test_plan_view_roundtrips_invalidation_and_bounds_it() -> None:
    now = datetime.now(UTC)
    inv = {"reason": "expired", "changes": [{"kind": "registry", "name": "gitlab"}]}
    view = {
        "id": str(uuid4()),
        "version": 1,
        "status": "invalidated",
        "content_hash": SHA,
        "content": {},
        "created_at": now,
        "expires_at": now,
        "invalidation": inv,
    }
    assert json.loads(PlanView.model_validate(view).model_dump_json())["invalidation"] == inv
    too_many = {**inv, "changes": [{"kind": "tool", "name": "t"}] * 21}
    with pytest.raises(ValidationError):
        PlanView.model_validate({**view, "invalidation": too_many})
