"""Régressions de l'éval live (P1-1) : un message libre pendant une question ouverte, et un tour
en échec qui doit toujours s'expliquer."""

from collections.abc import Sequence
from typing import Any

from foreman.core.events import ERROR_MESSAGES, ClarificationQuestion
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from support import NoReads, make_planner

ENVIRONMENT_QUESTION = ClarificationQuestion(
    id="q1-1",
    field="environment",
    prompt="Quel environnement ?",
    options=["staging", "production"],
    status="open",
)


class PlanningProvider:
    """Garde les messages reçus et propose un plan valide d'une étape."""

    def __init__(self) -> None:
        self.seen: list[ConversationMessage] = []

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.seen = list(messages)
        params = {"environment": "staging"}
        step = {"title": "Lister le DNS", "tool": "dns.list_records", "params": params}
        plan = {"title": "Plan", "summary": "Résumé", "environment": "staging", "steps": [step]}
        return ModelReply(text="Voici le plan.", tool_calls=(ToolCall("propose_plan", plan),))


class SilentInvalidAskProvider:
    """Aucun texte et un `ask_user` invalide (aucune question)."""

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        return ModelReply(text="", tool_calls=(ToolCall("ask_user", {"questions": []}),))


async def _play(provider: Any, message: str, questions: list[ClarificationQuestion]) -> list[Any]:
    log, projects = InMemoryEventLog(), InMemoryProjectStore()
    project_id = (await projects.create("p")).id
    await projects.set_open_questions(project_id, questions)
    service = TurnService(provider, log, make_planner(), projects, NoReads())
    await service.run(TurnRequest(DEV_USER_ID, project_id, message), service.begin(project_id))
    return [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]


async def test_a_free_message_closes_the_open_question_and_the_plan_goes_through() -> None:
    provider = PlanningProvider()
    events = await _play(provider, "ok", [ENVIRONMENT_QUESTION])

    assert events[-1]["data"] == {"status": "completed"}
    cards = [e["data"] for e in events if e["type"] == "card"]
    assert [c["kind"] for c in cards] == ["clarification", "plan"]
    assert cards[0]["questions"][0]["status"] == "deferred"
    # Le modèle sait quelle question restait ouverte ; il répond toujours au dernier message.
    assert provider.seen[-1].text == "ok"
    assert any("Quel environnement ?" in m.text for m in provider.seen[:-1])


async def test_a_refused_ask_user_fails_with_its_own_code_and_no_empty_message() -> None:
    events = await _play(SilentInvalidAskProvider(), "supprime les vieux dépôts", [])

    assert [e["type"] for e in events][2:] == ["error", "turn_status"]
    assert events[2]["data"] == {
        "code": "invalid_ask_user",
        "message": ERROR_MESSAGES["invalid_ask_user"],
    }
    assert events[3]["data"] == {"status": "failed"}
