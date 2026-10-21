"""Frontière d'envoi au modèle : masquage, erreurs opaques, choix de l'adaptateur."""

import json
import logging
import os
from collections.abc import Sequence
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr

from foreman.bootstrap.provider import ConfiguredProvider, choose_provider
from foreman.core.llm import LLM_KEY_ID, LLM_KEY_KIND, LLM_MODEL_ID, LLM_MODEL_KIND
from foreman.core.ports import ConversationMessage, ModelReply
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.infra.secrets import InMemorySecretStore, Keyring
from foreman.integrations.anthropic.models import load_connector
from foreman.integrations.anthropic.provider import AnthropicProvider
from support import make_planner

API_KEY = "sk-ant-api03-cle-de-test-0123456789abcdef"
PASSWORD = "hunter2-tres-secret"  # noqa: S105


class SpyProvider:
    def __init__(self, name: str = "spy") -> None:
        self.name = name
        self.seen: list[str] = []

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.seen.extend(m.text for m in messages)
        return ModelReply(text=self.name)


class ErrorEchoingTransport(httpx2.AsyncBaseTransport):
    """Refuse la requête (401) en répétant la clé reçue, comme le ferait un serveur bavard."""

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        echoed = request.headers.get("x-api-key", "")
        return httpx2.Response(401, json={"type": "error", "error": {"message": f"clé {echoed}"}})


async def configured_store() -> InMemorySecretStore:
    store = InMemorySecretStore(Keyring.of(os.urandom(32)))
    await store.put(LLM_KEY_ID, LLM_KEY_KIND, SecretStr(API_KEY), created_by="test")
    await store.put(LLM_MODEL_ID, LLM_MODEL_KIND, SecretStr("claude-sonnet-5-5"), created_by="test")
    return store


async def run_turn(provider: object, message: str) -> list[dict[str, object]]:
    log, project_id = InMemoryEventLog(), uuid4()
    service = TurnService(provider, log, make_planner(), InMemoryProjectStore())  # type: ignore[arg-type]
    await service.run(TurnRequest(DEV_USER_ID, project_id, message), service.begin(project_id))
    return [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]


async def test_the_model_only_sees_masked_history() -> None:
    spy = SpyProvider()
    await run_turn(spy, f"voici password={PASSWORD} et la clé {API_KEY}")
    sent = " ".join(spy.seen)
    assert PASSWORD not in sent and API_KEY not in sent and "[masqué]" in sent


async def test_an_sdk_error_never_reaches_events_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    http = httpx2.AsyncClient(transport=ErrorEchoingTransport())
    provider = AnthropicProvider(SecretLlmSettings(await configured_store()), http_client=http)
    events = await run_turn(provider, "salut")
    assert [e["type"] for e in events[2:]] == ["error", "turn_status"]
    assert events[2]["data"]["code"] == "internal_error"  # type: ignore[index]
    assert API_KEY not in json.dumps(events) + caplog.text
    await http.aclose()


async def test_ci_and_eval_force_the_replay_and_the_real_model_needs_a_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replay, real = SpyProvider("replay"), SpyProvider("real")
    store = await configured_store()
    message = [ConversationMessage("user", "salut")]
    monkeypatch.setenv("CI", "true")
    assert (
        await choose_provider(replay, store, force_replay=False).complete(message)
    ).text == "replay"
    monkeypatch.delenv("CI")
    assert (
        await choose_provider(replay, store, force_replay=True).complete(message)
    ).text == "replay"
    # Sans clé configurée : rejeu. Avec clé : le vrai provider seul, l'entrée `default` du rejeu
    # n'est jamais consultée.
    empty = InMemorySecretStore(Keyring.of(os.urandom(32)))
    assert (await ConfiguredProvider(replay, real, empty).complete(message)).text == "replay"
    assert (await ConfiguredProvider(replay, real, store).complete(message)).text == "real"
    assert (len(replay.seen), len(real.seen)) == (3, 1)  # le rejeu n'a pas servi avec la clé


def test_the_declared_model_list_has_prices() -> None:
    models = load_connector().models
    assert models and all(m.input_usd > 0 and m.output_usd > 0 for m in models)
