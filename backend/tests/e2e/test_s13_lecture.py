"""S13 de bout en bout (#295) : une question, une lecture GitLab, une réponse texte.

Sécurité : une écriture appelée directement dans le chat reste refusée (`unknown_tool`). Budget :
le 6e tour d'outils arrête le tour proprement.
"""

from dataclasses import replace
from typing import Any

import pytest
from s13_run import run_s13

from foreman.core.planning import Planner
from foreman.core.ports import ModelReply, ToolCall
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


async def test_s13_one_question_one_read_one_text_answer() -> None:
    run = await run_s13()
    assert {e.type for e in run.events} == {"message", "tool_call", "turn_status"}  # 0 carte
    calls = [e.data for e in run.events if e.type == "tool_call"]
    assert [(c.tool, c.outcome) for c in calls] == [("gitlab.list_groups", "ok")]  # type: ignore[union-attr]
    messages = [e.data.text for e in run.events if e.type == "message"]  # type: ignore[union-attr]
    assert len(messages) == 2 and "Legacy" in messages[1]  # question, puis réponse finale seule
    audit = await run.state.stores.audit.list_for_project(run.project_id)
    assert [(a.rule_id, a.decision) for a in audit] == [("R1-lecture", "executed")]


class ScriptedProvider:
    def __init__(self, reply: ModelReply) -> None:
        self.reply = reply

    async def complete(self, messages: object) -> ModelReply:
        return self.reply


class SlowReads:
    """Gateway dont chaque lecture consomme `cost_s` secondes de l'horloge (fausse) du tour."""

    def __init__(self, inner: Any, clock: list[float], cost_s: float) -> None:
        self.inner, self.clock, self.cost_s = inner, clock, cost_s

    def __call__(self) -> float:
        return self.clock[0]

    async def read(self, call: Any) -> Any:
        out = await self.inner.read(call)
        self.clock[0] += self.cost_s
        return out


async def play(
    reply: ModelReply, read_cost_s: float = 0.0
) -> tuple[list[str], list[int], list[str]]:
    """Joue un tour sur la vraie gateway et le faux GitLab ; rend codes d'erreur et groupes."""
    state = (await run_s13()).state
    catalog = load_catalog(environment="staging")
    budget = catalog.policy.budgets.per_turn.model_copy(update={"max_model_calls": 6})
    budgets = catalog.policy.budgets.model_copy(update={"per_turn": budget})
    catalog = replace(catalog, policy=catalog.policy.model_copy(update={"budgets": budgets}))
    stores, clock = in_memory_stores()[1], [0.0]
    slow = SlowReads(state.gateway, clock, read_cost_s)
    log, project_id = InMemoryEventLog(), (await state.projects.create("P")).id
    service = TurnService(
        ScriptedProvider(reply),
        log,
        Planner(catalog, stores.plans, stores.registry),
        InMemoryProjectStore(),
        slow,  # type: ignore[arg-type]
        clock=slow,
    )
    member = next(m for m in state.dev_members if m.name == "dev")
    request = TurnRequest(user_id=member.user_id, project_id=project_id, message="salut")
    await service.run(request, service.begin(project_id))
    events = await log.read_after(project_id, 0)
    codes = [e.data.code for e in events if e.type == "error"]  # type: ignore[union-attr]
    texts = [e.data.text for e in events if e.type == "message"]  # type: ignore[union-attr]
    groups = sorted(state.gateway._adapters["gitlab"].groups)  # type: ignore[union-attr]
    return codes, groups, texts


async def test_a_sixth_tool_round_stops_with_budget_exceeded() -> None:
    codes, _, _ = await play(ModelReply("", (ToolCall("gitlab.list_groups", {}),)))
    assert codes == ["budget_exceeded"]


async def test_a_write_called_directly_in_chat_is_unknown_tool_and_creates_no_group() -> None:
    write = ModelReply(
        "", (ToolCall("gitlab.create_group", {"parent_group_id": 1000, "name": "x"}),)
    )
    codes, groups, _ = await play(write)
    assert codes == ["unknown_tool"] and groups == (await play(ModelReply("ok")))[1]


async def test_reads_that_use_up_the_turn_duration_stop_the_turn() -> None:
    reply = ModelReply("", (ToolCall("gitlab.list_groups", {}),))
    codes, _, texts = await play(reply, read_cost_s=121.0)
    assert codes == ["budget_exceeded"] and "durée dépassée" in texts[-1]
