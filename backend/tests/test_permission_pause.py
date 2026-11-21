"""Lecture du chat refusée pour droit manquant : carte « Droit manquant », modèle non rappelé."""

from collections.abc import Sequence
from typing import Any, get_args
from uuid import uuid4

import pytest

from foreman.core.events import ReadErrorCode
from foreman.core.gateway.errors import CallDenied, CallFailed, DenialCode, FailureCode
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from support import make_planner


class CountingListGroupsProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.calls += 1
        return ModelReply(text="", tool_calls=(ToolCall("gitlab.list_groups", {}, "c1"),))


class MissingRightGateway:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def read(self, call: Any) -> dict[str, Any]:
        raise self.error


@pytest.mark.parametrize(
    "error", [CallFailed("permission_missing"), CallDenied("permission_missing")]
)
async def test_missing_right_stops_the_turn_on_a_permission_card(error: Exception) -> None:
    log, provider, project_id = InMemoryEventLog(), CountingListGroupsProvider(), uuid4()
    gateway = MissingRightGateway(error)
    service = TurnService(
        provider,
        log,
        make_planner(),
        InMemoryProjectStore(),
        gateway,  # type: ignore[arg-type]
    )
    await service.run(TurnRequest(DEV_USER_ID, project_id, "liste"), service.begin(project_id))

    events = [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]
    assert [e["type"] for e in events][2:] == ["tool_call", "card", "turn_status"]
    assert events[2]["data"] == {
        "tool": "gitlab.list_groups",
        "outcome": "error",
        "code": "permission_missing",
    }
    card = events[3]["data"]
    assert (card["kind"], card["token"], card["scopes"]) == ("permission", "read", ["read_api"])
    assert events[4]["data"] == {"status": "completed"}
    assert provider.calls == 1
    service.begin(project_id)  # le verrou est relâché


def test_the_tool_call_error_codes_cover_every_gateway_code() -> None:
    """La liste fermée de `tool_call.code` est recopiée : elle doit suivre la gateway."""
    gateway_codes = set(get_args(DenialCode)) | set(get_args(FailureCode))
    assert gateway_codes | {"limit_reached"} == set(get_args(ReadErrorCode))
