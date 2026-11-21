"""Régression (éval live, P2-1) : le modèle annonçait « 9 groupes en échec » puis « 14 » pour 15
lectures. Les comptes d'une ronde sont calculés par le code et envoyés avec les résultats."""

import json
from collections.abc import Sequence
from typing import Any
from uuid import uuid4

from foreman.core.gateway.errors import CallFailed
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import MAX_READS_PER_ROUND, TurnRequest, TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.integrations.anthropic.provider import wire_messages
from support import make_planner


class InventoryProvider:
    """Une ronde de lectures au-delà de la limite, puis du texte ; garde l'historique reçu."""

    def __init__(self) -> None:
        self.seen: list[ConversationMessage] = []

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.seen = list(messages)
        if any(m.tool_results for m in messages):
            return ModelReply(text="Bilan.")
        names = ["gitlab.get_project", *["gitlab.list_groups"] * MAX_READS_PER_ROUND]
        return ModelReply(
            text="", tool_calls=tuple(ToolCall(n, {}, f"c{i}") for i, n in enumerate(names))
        )


class GetProjectFailsGateway:
    async def read(self, call: Any) -> dict[str, Any]:
        if call.tool == "gitlab.get_project":
            raise CallFailed("adapter_error")
        return {"groups": []}

    async def refuse_read(self, call: Any, code: str) -> None:
        return None


async def test_the_model_receives_counts_computed_by_the_code_with_the_results() -> None:
    provider, project_id = InventoryProvider(), uuid4()
    service = TurnService(
        provider, InMemoryEventLog(), make_planner(), InMemoryProjectStore(),
        GetProjectFailsGateway(),  # type: ignore[arg-type]
    )  # fmt: skip
    await service.run(TurnRequest(DEV_USER_ID, project_id, "inventaire"), service.begin(project_id))

    results = wire_messages(provider.seen)[-1]["content"]
    summary = json.loads(results[-1]["text"])  # bloc texte après les tool_result
    assert summary["bilan_lectures"] == {
        "demandees": MAX_READS_PER_ROUND + 1,
        "lues": MAX_READS_PER_ROUND - 1,
        "en_erreur": 1,
        "non_interrogees": 1,
    }
