"""Réponses enregistrées du modèle : rejouées dans le vrai AnthropicProvider, sans réseau."""

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr

from foreman.core.llm import LLM_KEY_ID, LLM_KEY_KIND, LLM_MODEL_ID, LLM_MODEL_KIND
from foreman.core.pricing import ModelPrice
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.llm_recording import RecordingRefused, build_recording, load_recording
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.infra.secrets import InMemorySecretStore, Keyring
from foreman.integrations.anthropic.provider import AnthropicProvider
from support import make_planner

REAL_DIR = Path(__file__).parents[2] / "catalog" / "recordings" / "real"
API_KEY = "sk-ant-api03-cle-de-test-0123456789abcdef"


class RecordedTransport(httpx2.AsyncBaseTransport):
    """Répond à toute requête par la réponse enregistrée ; garde les requêtes vues."""

    def __init__(self, message: dict[str, Any]) -> None:
        self.message = message
        self.requests: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.message)


async def settings_for(model: str) -> SecretLlmSettings:
    store = InMemorySecretStore(Keyring.of(os.urandom(32)))
    await store.put(LLM_KEY_ID, LLM_KEY_KIND, SecretStr(API_KEY), created_by="test")
    await store.put(LLM_MODEL_ID, LLM_MODEL_KIND, SecretStr(model), created_by="test")
    return SecretLlmSettings(store)


async def test_s1_passes_through_the_real_provider_on_a_recorded_response() -> None:
    recording = load_recording(REAL_DIR / "s01-synthetic.json")  # synthétique : voir "synthetic"
    transport = RecordedTransport(recording["message"])
    http = httpx2.AsyncClient(transport=transport)
    provider = AnthropicProvider(await settings_for(recording["model"]), http_client=http)
    prices = {recording["model"]: ModelPrice(input_usd=Decimal(2), output_usd=Decimal(10))}
    log, project_id = InMemoryEventLog(), uuid4()
    service = TurnService(provider, log, make_planner(), InMemoryProjectStore(), prices=prices)

    await service.run(
        TurnRequest(DEV_USER_ID, project_id, "Crée Safe Eat"), service.begin(project_id)
    )

    events = [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]
    assert [e["type"] for e in events] == [
        "message",
        "turn_status",
        "message",
        "card",
        "turn_status",
    ]
    assert len(events[3]["data"]["steps"]) == 8 and events[3]["data"]["status"] == "proposed"
    assert events[4]["data"] == {"status": "completed"}
    # Contraintes du modèle : choix d'outil automatique, arguments stricts, effort explicite.
    body = json.loads(transport.requests[0].content)
    assert body["tool_choice"] == {"type": "auto"}
    assert all(tool["strict"] is True for tool in body["tools"])
    assert body["output_config"] == {"effort": "medium"}
    await http.aclose()


def test_a_recording_with_a_secret_pattern_is_refused(tmp_path: Path) -> None:
    leaking = {"version": 1, "message": {"content": [{"type": "text", "text": f"clé {API_KEY}"}]}}
    path = tmp_path / "fuite.json"
    path.write_text(json.dumps(leaking), encoding="utf-8")
    with pytest.raises(RecordingRefused) as refused:
        load_recording(path)
    assert API_KEY not in str(refused.value)
    # À l'écriture, le motif est masqué avant le contrôle : l'enregistrement produit est propre.
    message = {"usage": {"input_tokens": 1}, "content": [{"type": "text", "text": API_KEY}]}
    built = build_recording("m", message, last_user_sha256="0" * 64)
    assert API_KEY not in json.dumps(built)


def test_committed_recordings_are_clean() -> None:
    for path in REAL_DIR.glob("*.json"):
        load_recording(path)
