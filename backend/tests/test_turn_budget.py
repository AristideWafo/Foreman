"""Budget par tour : un dépassement arrête le tour proprement et le modèle n'est plus rappelé."""

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from foreman.core.catalog import TurnBudget
from foreman.core.planning import Planner
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.pricing import ModelPrice, Usage
from foreman.core.store import DEV_USER_ID
from foreman.core.turn import TurnRequest, TurnService
from foreman.core.turn_budget import TurnMeter
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores
from support import NoReads

MODEL = "modele-test"
PRICES = {MODEL: ModelPrice(input_usd=Decimal(3), output_usd=Decimal(10))}
LIMITS = TurnBudget(max_model_calls=2, max_tokens=1000, max_cost_eur=0.5, max_seconds=60)


class ManualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class CostlyProvider:
    """Répond avec un plan valide ; `usage` et durée simulée choisis par le test."""

    def __init__(self, usage: Usage, clock: ManualClock, takes_s: float = 0.0) -> None:
        self.usage, self.clock, self.takes_s = usage, clock, takes_s
        self.calls = 0

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        self.calls += 1
        self.clock.now += self.takes_s
        step = {"title": "Lister", "tool": "dns.list_records", "params": {"environment": "staging"}}
        plan = {"title": "P", "summary": "R", "environment": "staging", "steps": [step]}
        return ModelReply("ok", (ToolCall("propose_plan", plan),), self.usage)


async def play(provider: CostlyProvider, clock: ManualClock, limits: TurnBudget) -> list[str]:
    catalog = load_catalog(environment="staging")
    budgets = catalog.policy.budgets.model_copy(update={"per_turn": limits})
    catalog = replace(catalog, policy=catalog.policy.model_copy(update={"budgets": budgets}))
    stores = in_memory_stores()[1]
    planner = Planner(catalog, stores.plans, stores.registry)
    log, project_id = InMemoryEventLog(), uuid4()
    service = TurnService(
        provider, log, planner, InMemoryProjectStore(), NoReads(), prices=PRICES, clock=clock
    )
    await service.run(
        TurnRequest(user_id=DEV_USER_ID, project_id=project_id, message="salut"),
        service.begin(project_id),
    )
    events = await log.read_after(project_id, 0)
    return [e.type if e.type != "error" else f"error:{e.data.code}" for e in events]  # type: ignore[union-attr]


STOPPED = ["message", "turn_status", "message", "error:budget_exceeded", "turn_status"]


@pytest.mark.parametrize(
    ("usage", "takes_s", "limits"),
    [
        (Usage(MODEL, 100, 1_000_000), 0.0, LIMITS.model_copy(update={"max_tokens": 10**7})),
        (Usage(MODEL, 800, 800), 0.0, LIMITS),  # jetons
        (Usage(MODEL, 1, 1), 61.0, LIMITS),  # durée
    ],
    ids=["cost", "tokens", "duration"],
)
async def test_an_exceeded_turn_stops_with_budget_exceeded_and_runs_no_tool(
    usage: Usage, takes_s: float, limits: TurnBudget
) -> None:
    clock = ManualClock()
    provider = CostlyProvider(usage, clock, takes_s)
    assert await play(provider, clock, limits) == STOPPED  # aucune carte : le plan n'est pas posé
    assert provider.calls == 1


def test_the_model_is_not_called_again_once_a_limit_is_passed_or_calls_are_spent() -> None:
    clock = ManualClock()
    meter = TurnMeter(LIMITS.model_copy(update={"max_tokens": 10**7}), PRICES, clock)
    assert meter.admit() is None
    meter.record(Usage(MODEL, 1, 1_000_000))  # ~9,2 EUR pour 0,5 EUR de budget
    assert meter.admit() == "cost"
    assert meter.calls == 1  # le refus ne compte pas
    spent = TurnMeter(LIMITS.model_copy(update={"max_model_calls": 1}), PRICES, clock)
    assert (spent.admit(), spent.admit()) == (None, "calls")
