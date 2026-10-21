"""Indicateur (ADR 0002, couche 6) : le modèle corrige-t-il l'erreur avec le seul extrait filtré ?

Rejeu sans réseau des scénarios d'échec S3 à S9 (`catalog/evals/diagnostic-s3-s9.yaml`). Le modèle
ne lit que ce que `model_history` montre d'un `execution_diagnostic` (code, attendu, observé, sonde,
extrait masqué). La réponse enregistrée est liée à cette entrée par son sha256 : si l'entrée change
(nouveau format, nouveau masquage), le cas est « périmé », à réenregistrer (recalculer
`input_sha256` avec `model_input`), jamais compté comme réussi. Corrigé = la réponse appelle l'outil
attendu.

Limite assumée : les réponses du dépôt sont SYNTHÉTIQUES (écrites à la main, comme
`s01-synthetic`). Le taux mesure donc la chaîne (masquage, extrait, historique), pas encore le
vrai modèle ; `score` accepte n'importe quel `Provider`, pour le brancher sur `evals.yml`.

Rapport : stdout et, en CI, le résumé de l'étape (`GITHUB_STEP_SUMMARY`). Informatif : sortie 0.
"""

import asyncio
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Final
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from foreman.core.catalog import parse_yaml_mapping
from foreman.core.events import ExecutionDiagnosticData, ToolDiagnostic, make_event
from foreman.core.ports import ConversationMessage, ModelReply, Provider, ToolCall
from foreman.core.turn import model_history
from foreman.infra.replay_provider import sha256_of

EVALS_FILE: Final = Path(__file__).resolve().parents[2] / "catalog/evals/diagnostic-s3-s9.yaml"
SCENARIOS: Final = tuple(f"S{n}" for n in range(3, 10))
_PROJECT: Final = UUID(int=1)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Call(_Strict):
    name: str
    arguments: dict[str, JsonValue] = {}


class _Reply(_Strict):
    text: str
    tool_calls: list[_Call] = []


class Case(_Strict):
    id: str
    scenario: Annotated[str, Field(pattern=r"^S[3-9]$")]
    tool: str
    step: int = 1
    diagnostic: ToolDiagnostic
    input_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    expect_tool: str  # l'outil que la réponse corrective doit appeler
    reply: _Reply


class _File(_Strict):
    version: Annotated[int, Field(strict=True)]
    cases: list[Case]


def load_cases(path: Path = EVALS_FILE) -> list[Case]:
    return _File.model_validate(parse_yaml_mapping(path.read_bytes(), path.name)).cases


def model_input(case: Case) -> list[ConversationMessage]:
    """Ce que le modèle lit de l'échec : passe par le chemin réel (`model_history`)."""
    data = ExecutionDiagnosticData(
        card_id="execution-eval", step=case.step, tool=case.tool, diagnostic=case.diagnostic
    )
    event = make_event(1, _PROJECT, uuid4(), data)
    return model_history([event])


class RecordedModel:
    """`Provider` rejoué : la réponse du cas dont l'entrée a ce sha256, sinon rien."""

    def __init__(self, cases: list[Case]) -> None:
        self._by_hash = {c.input_sha256: c.reply for c in cases}

    async def complete(self, messages: list[ConversationMessage]) -> ModelReply:  # type: ignore[override]
        reply = self._by_hash.get(sha256_of(messages[-1].text))
        if reply is None:
            return ModelReply(text="")  # entrée inconnue : le cas est périmé
        calls = tuple(ToolCall(c.name, dict(c.arguments)) for c in reply.tool_calls)
        return ModelReply(text=reply.text, tool_calls=calls)


@dataclass(frozen=True, slots=True)
class Outcome:
    case: Case
    fixed: bool
    stale: bool


async def score(cases: list[Case], provider: Provider) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for case in cases:
        messages = model_input(case)
        stale = sha256_of(messages[-1].text) != case.input_sha256
        reply = await provider.complete(messages)
        fixed = not stale and any(c.name == case.expect_tool for c in reply.tool_calls)
        outcomes.append(Outcome(case, fixed, stale))
    return outcomes


def report(outcomes: list[Outcome]) -> str:
    """Tableau Markdown par scénario, puis le taux global (périmés comptés comme non corrigés)."""
    by_scenario: dict[str, list[Outcome]] = defaultdict(list)
    for o in outcomes:
        by_scenario[o.case.scenario].append(o)
    rows = ["| Scénario | Corrigés | Périmés |", "| --- | --- | --- |"]
    for name in SCENARIOS:
        found = by_scenario.get(name, [])
        fixed, stale = sum(o.fixed for o in found), sum(o.stale for o in found)
        rows.append(f"| {name} | {fixed}/{len(found)} | {stale} |")
    fixed = sum(o.fixed for o in outcomes)
    rate = fixed / len(outcomes) if outcomes else 0.0
    head = f"## Diagnostic : correction avec le seul extrait filtré ({datetime.now(UTC):%Y-%m-%d})"
    return "\n".join(
        [head, "", *rows, "", f"**Taux : {fixed}/{len(outcomes)} = {rate:.0%}** (informatif)"]
    )


def main() -> None:
    text = report(asyncio.run(score(load_cases(), RecordedModel(load_cases()))))
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(text + "\n")


if __name__ == "__main__":
    main()
