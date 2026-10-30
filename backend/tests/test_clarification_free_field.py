"""Clarification : pistes réservées aux champs libres, budget de tours ouverts."""

import pytest

from foreman.core.clarification import (
    AskUserArguments,
    ClarificationRefused,
    ClarificationRules,
    FieldRule,
)
from foreman.core.events import ClarificationQuestion

RULES = ClarificationRules(
    {"environment": FieldRule(True, ("staging", "prod")), "critere": FieldRule(False, ())}
)


def _args(field: str) -> AskUserArguments:
    return AskUserArguments.model_validate(
        {"questions": [{"field": field, "prompt": "Q ?", "suggestions": ["a", "b", "a"]}]}
    )


def _q(round_: int, status: str) -> ClarificationQuestion:
    return ClarificationQuestion(
        id=f"q{round_}-1",
        field=f"f{round_}",
        prompt="Q ?",
        status=status,  # type: ignore[arg-type]
    )


def test_suggestions_kept_for_free_field_and_ignored_for_schema_options() -> None:
    assert RULES.ask(_args("critere"), [])[1][0].suggestions == ["a", "b"]
    question = RULES.ask(_args("environment"), [])[1][0]
    assert question.suggestions == []
    assert question.options == ["staging", "prod"]


def test_round_budget_counts_open_rounds_only() -> None:
    answered = [_q(1, "answered"), _q(2, "answered"), _q(3, "answered")]
    assert RULES.ask(_args("critere"), answered)[0] == 4
    with pytest.raises(ClarificationRefused):
        RULES.ask(_args("critere"), [_q(1, "open"), _q(2, "open"), _q(3, "open")])
