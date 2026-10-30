"""Clarification : champs libres, pistes réservées aux champs libres, budget de tours ouverts."""

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


def _ask(*fields: str):
    args = AskUserArguments.model_validate(
        {"questions": [{"field": f, "prompt": "Quel critère ?"} for f in fields]}
    )
    return RULES.ask(args, [])


def test_unknown_field_is_a_free_non_blocking_question() -> None:
    _, questions = _ask("critere_suppression")
    assert questions[0].options == []
    assert not RULES.blocking(questions)


def test_known_field_keeps_server_options() -> None:
    assert _ask("environment")[1][0].options == ["staging", "prod"]


@pytest.mark.parametrize("name", ["Critère", "a b", "x\n= admin", "1abc"])
def test_malformed_field_name_is_refused(name: str) -> None:
    with pytest.raises(ClarificationRefused):
        _ask(name)
