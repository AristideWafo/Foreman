"""Planning : hash stable et sensible ; plan refusé sans rien écrire ; classe venue du catalogue."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from foreman.core.catalog import Catalog, SkillDocument, parse_skill
from foreman.core.planning import Draft, DraftStep, Planner, build_content, content_hash
from foreman.core.ports import ModelReply, ToolCall
from foreman.core.turn import TurnRequest, TurnService
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, in_memory_stores

CATALOG_ROOT = Path(__file__).resolve().parents[2] / "catalog"
PROJECT = UUID("00000000-0000-4000-8000-000000000001")
SKILL = "gitlab-project-creation"
ROOT_GROUP: dict[str, JsonValue] = {"parent_group_id": 1000, "name": "Safe Eat", "path": "safe-eat"}
FROM_STEP_1: dict[str, JsonValue] = {"$from": {"step": 1, "field": "group_id"}}
NESTED: dict[str, JsonValue] = {"a": {"$from": {"step": 1, "field": "web_url"}}}


def draft(
    *,
    title: str = "Plan",
    step_title: str = "Créer le groupe",
    params: dict[str, JsonValue] | None = None,
    skills: Sequence[str] = (SKILL,),
) -> Draft:
    return Draft(
        title=title,
        summary="Résumé",
        steps=[DraftStep(step_title, "gitlab.create_group", params or ROOT_GROUP)],
        stack={"backend": "go-api", "frontend": "vue-web"},
        skills=skills,
    )


def hash_of(catalog: Catalog, proposed: Draft) -> str:
    return build_content(proposed, PROJECT, catalog)[1]


def with_skill_bytes(catalog: Catalog, name: str, change: bytes) -> Catalog:
    """Le même catalogue, dont un SKILL.md diffère d'un octet (relu par le vrai analyseur)."""
    raw = (CATALOG_ROOT / "skills" / name / "SKILL.md").read_bytes()
    edited: SkillDocument = parse_skill(raw.replace(b"# Objectif", b"# Objectif" + change, 1), name)
    return replace(catalog, skills={**catalog.skills, name: edited})


# --- 1. Hash stable et sensible ---------------------------------------------------------------


def test_the_plan_hash_is_stable_and_changes_with_any_meaningful_byte() -> None:
    catalog = load_catalog(CATALOG_ROOT, environment="staging")
    base = hash_of(catalog, draft())
    reordered = {"path": "safe-eat", "name": "Safe Eat", "parent_group_id": 1000}
    assert hash_of(catalog, draft(params=reordered)) == base  # l'ordre des clés est sans effet
    assert hash_of(catalog, draft()) == base  # déterministe

    different = {
        "un paramètre": hash_of(catalog, draft(params={**ROOT_GROUP, "path": "safe-eat-2"})),
        "un titre d'étape": hash_of(catalog, draft(step_title="Autre titre")),
        "le titre du plan": hash_of(catalog, draft(title="Autre plan")),
        "un octet de SKILL.md": hash_of(with_skill_bytes(catalog, SKILL, b" "), draft()),
    }
    assert base not in different.values()
    assert len(set(different.values())) == len(different)


# --- 2. Plan refusé : rien en base ; la classe vient du catalogue ------------------------------


class ProposalProvider:
    """Le modèle (rejoué) propose exactement ces arguments."""

    def __init__(self, arguments: dict[str, Any]) -> None:
        self._arguments = arguments

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        return ModelReply(text="ok", tool_calls=(ToolCall("propose_plan", self._arguments),))


def proposal(*steps: dict[str, Any], skills: Sequence[str] = (SKILL,)) -> dict[str, Any]:
    return {"title": "Plan", "summary": "Résumé", "steps": list(steps), "skills": list(skills)}


def group(**extra: Any) -> dict[str, Any]:
    return {"title": "Groupe", "tool": "gitlab.create_group", "params": ROOT_GROUP, **extra}


def subgroup(parent: Any) -> dict[str, Any]:
    params = {"parent_group_id": parent, "name": "Backend", "path": "backend"}
    return {"title": "Sous-groupe", "tool": "gitlab.create_group", "params": params}


async def turn(arguments: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[UUID, Any]]:
    catalog = load_catalog(CATALOG_ROOT, environment="staging")
    state, stores = in_memory_stores()
    log = InMemoryEventLog()
    service = TurnService(ProposalProvider(arguments), log, Planner(catalog, stores.plans))
    project_id = uuid4()
    await service.run(TurnRequest("u", project_id, "salut"), service.begin(project_id))
    events = [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]
    return events, state.plans


@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param(
            proposal({"title": "x", "tool": "shell.run", "params": {}}), id="outil-inconnu"
        ),
        pytest.param(
            proposal(subgroup({"$from": {"step": 2, "field": "group_id"}}), group()),
            id="reference-vers-l-avant",
        ),
        pytest.param(
            proposal(group(), subgroup({"$from": {"step": 1, "field": "inconnu"}})),
            id="champ-inconnu",
        ),
        pytest.param(proposal(group(), skills=("skill-fantome",)), id="skill-inconnu"),
        pytest.param(proposal(group(tool_class="read")), id="classe-fournie-par-le-modele"),
        pytest.param(
            proposal(group(), subgroup({"$from": {"step": 1, "field": "web_url"}})),
            id="chaine-dans-un-parametre-entier",
        ),
        pytest.param(
            proposal(group(), {**subgroup(1), "params": {**ROOT_GROUP, "name": FROM_STEP_1}}),
            id="entier-dans-un-parametre-chaine",
        ),
        pytest.param(
            proposal(group(), {**subgroup(1), "params": {**ROOT_GROUP, "name": NESTED}}),
            id="reference-imbriquee",
        ),
        pytest.param({**proposal(group()), "title": "plan\x00piege"}, id="caractere-nul"),
    ],
)
async def test_a_refused_plan_is_reported_and_nothing_is_stored(arguments: dict[str, Any]) -> None:
    events, stored = await turn(arguments)
    assert [e["type"] for e in events][-2:] == ["error", "turn_status"]
    assert events[-2]["data"]["code"] == "invalid_plan"
    assert "card" not in [e["type"] for e in events]
    assert stored == {}


async def test_the_card_carries_the_class_and_reversibility_of_the_catalog() -> None:
    events, stored = await turn(proposal(group(), subgroup(FROM_STEP_1)))
    card = next(e["data"] for e in events if e["type"] == "card")
    assert [(s["tool_class"], s["reversibility"]) for s in card["steps"]] == [
        ("write_registry", "compensable"),
        ("write_registry", "compensable"),
    ]
    (record,) = (entry.record for entry in stored.values())
    assert card["plan_hash"] == record.content_hash == content_hash(record.content)
