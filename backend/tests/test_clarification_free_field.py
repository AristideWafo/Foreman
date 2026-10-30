import pytest

from foreman.core.clarification import (
    AskUserArguments,
    ClarificationRefused,
    ClarificationRules,
    FieldRule,
)

RULES = ClarificationRules({"environment": FieldRule(True, ("staging", "prod"))})


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
