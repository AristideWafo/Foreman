import asyncio
import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

import pytest

from foreman.core.ports import ModelReply, Provider, ToolCall
from foreman.core.turn import TurnInProgress, TurnRequest, TurnService
from foreman.infra.file_catalog import catalog_dir_from_env
from foreman.infra.in_memory import InMemoryEventLog
from foreman.infra.replay_provider import ReplayProvider

USER_TEXT_MARKER = "mot-de-passe-de-l-utilisateur"
ERROR_MARKER = "secret-interne postgres://user:pass@db"


class FakeProvider:
    """Fake nommé : répond « ok » et propose un plan valide d'une étape."""

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        plan = {"title": "Plan", "summary": "Résumé", "steps": [{"title": "Étape"}]}
        return ModelReply(text="ok", tool_calls=(ToolCall("propose_plan", plan),))


class ExplodingProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        raise RuntimeError(ERROR_MARKER)


class UnknownToolProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        return ModelReply(text="ok", tool_calls=(ToolCall("run_shell", {"cmd": "rm -rf /"}),))


class InvalidPlanProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        return ModelReply(text="ok", tool_calls=(ToolCall("propose_plan", {"title": 1}),))


class GatedProvider:
    """Reste bloqué dans `complete` jusqu'à ce que le test le libère."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        self.started.set()
        await self.release.wait()
        return ModelReply(text="ok")


async def play(provider: Provider, message: str = "salut") -> list[dict[str, Any]]:
    log = InMemoryEventLog()
    project_id = uuid4()
    service = TurnService(provider, log)
    request = TurnRequest(user_id="u", project_id=project_id, message=message)
    await service.run(request, service.begin(project_id))
    return [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]


def types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


async def test_turn_emits_the_contract_sequence_with_contiguous_seq() -> None:
    events = await play(FakeProvider())
    assert types(events) == ["message", "turn_status", "message", "card", "turn_status"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert len({e["turn_id"] for e in events}) == 1
    assert events[0]["data"] == {"role": "user", "text": "salut"}
    assert events[1]["data"] == {"status": "running"}
    assert events[2]["data"] == {"role": "assistant", "text": "ok"}
    assert events[3]["data"]["kind"] == "plan"
    assert [s["status"] for s in events[3]["data"]["steps"]] == ["pending"]
    assert events[4]["data"] == {"status": "completed"}


async def test_the_replayed_s01_turn_proposes_a_seven_step_pending_plan() -> None:
    events = await play(ReplayProvider.s01(catalog_dir_from_env()), "Crée Safe Eat")
    assert types(events) == ["message", "turn_status", "message", "card", "turn_status"]
    assert events[3]["data"]["kind"] == "plan"
    assert [s["title"] for s in events[3]["data"]["steps"]][:2] == [
        "Créer le groupe safe-eat",
        "Créer le sous-groupe backend",
    ]
    assert [s["status"] for s in events[3]["data"]["steps"]] == ["pending"] * 7


async def test_provider_exception_never_reaches_the_events() -> None:
    events = await play(ExplodingProvider(), USER_TEXT_MARKER)
    assert types(events[2:]) == ["error", "turn_status"]
    assert events[2]["data"]["code"] == "internal_error"
    assert events[3]["data"] == {"status": "failed"}
    failure_json = json.dumps(events[2:])
    assert ERROR_MARKER not in failure_json
    assert USER_TEXT_MARKER not in failure_json


async def test_unknown_tool_is_reported_and_never_executed() -> None:
    events = await play(UnknownToolProvider())
    assert types(events) == ["message", "turn_status", "message", "error", "turn_status"]
    assert events[3]["data"]["code"] == "unknown_tool"
    assert events[4]["data"] == {"status": "failed"}


async def test_invalid_plan_arguments_produce_no_card() -> None:
    events = await play(InvalidPlanProvider())
    assert "card" not in types(events)
    assert events[3]["data"]["code"] == "internal_error"


async def test_only_one_turn_at_a_time_per_project_and_the_guard_is_released() -> None:
    provider, log = GatedProvider(), InMemoryEventLog()
    service = TurnService(provider, log)
    project_id, other_id = uuid4(), uuid4()

    first = service.begin(project_id)
    running = asyncio.create_task(
        service.run(TurnRequest("u", project_id, "un"), first), name="premier-tour"
    )
    await asyncio.wait_for(provider.started.wait(), timeout=5)
    with pytest.raises(TurnInProgress):
        service.begin(project_id)
    service.release(project_id, uuid4())  # un autre jeton ne libère rien
    with pytest.raises(TurnInProgress):
        service.begin(project_id)
    service.begin(other_id)  # un autre projet n'est pas bloqué

    provider.release.set()
    await asyncio.wait_for(running, timeout=5)
    service.begin(project_id)  # libéré à la fin du tour


async def test_silent_provider_times_out_and_frees_the_project() -> None:
    """Sans délai, un fournisseur muet laisserait le projet en 409 pour toujours."""
    log = InMemoryEventLog()
    project_id = uuid4()
    service = TurnService(GatedProvider(), log, provider_timeout_s=0.05)
    turn = service.run(
        TurnRequest(user_id="u", project_id=project_id, message="salut"),
        service.begin(project_id),
    )
    await asyncio.wait_for(turn, timeout=2)  # échec net si le délai du fournisseur disparaît
    events = [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]
    assert types(events)[-2:] == ["error", "turn_status"]
    assert events[-1]["data"]["status"] == "failed"
    service.begin(project_id)  # la garde est libérée : pas de TurnInProgress
