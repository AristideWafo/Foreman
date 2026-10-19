"""Planning : du plan proposé par le modèle au plan haché, persisté, que le développeur valide.

Le modèle propose des titres, des outils et des paramètres ; il ne décide ni de la classe, ni de la
réversibilité, ni des clés d'idempotence (venues du catalogue) ni des empreintes (calculées ici).
Le contenu canonique (`PlanContent`) est sérialisé en JSON trié et haché en `sha256:<hex>` ; c'est
ce hash que l'approbation vise. Hors du hash : `id`, `version`, `expires_at`, `status` (portés par
l'enregistrement du plan, que le dépôt attribue).

Un plan invalide lève `InvalidPlan` (message fixe, aucun détail du modèle) et n'écrit rien.
"""

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from foreman.core.catalog import DRAFT_ALLOWED_ENVIRONMENTS, Catalog, SkillStatus, ToolDefinition
from foreman.core.events import (
    CardStep,
    ExpectedResource,
    PlanCardData,
    Reversibility,
    Sha256,
    SkillRef,
    ToolClass,
)
from foreman.core.policy.matrix import effective_level
from foreman.core.references import (
    MAX_DEPTH,
    REF_KEY,
    UnresolvedReference,
    is_reference,
    parse_reference,
)
from foreman.core.store import NewPlan, PlanRecord, PlanStore

PLAN_SCHEMA: Final = "foreman.plan/1"
MAX_STEPS: Final = 20
MAX_PLAN_BYTES: Final = 64 * 1024
MAX_KEY_CHARS: Final = 300
PLAN_TTL: Final = timedelta(hours=24)
FALLBACK_LEVEL: Final = 2
EXECUTION_ID_PLACEHOLDER: Final = "{execution_id}"  # substitué à l'approbation
_PLACEHOLDER: Final = re.compile(r"\{([^{}]*)\}")


class InvalidPlan(Exception):
    """Le plan proposé est refusé. Message fixe : ni le contenu du modèle ni la raison."""

    def __init__(self) -> None:
        super().__init__("plan invalide")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PlanStepContent(_Strict):
    seq: Annotated[int, Field(ge=1, le=MAX_STEPS)]
    title: Annotated[str, Field(max_length=200)]
    tool: str
    tool_version: str
    tool_class: ToolClass
    reversibility: Reversibility
    params: dict[str, JsonValue]
    idempotency_key: Annotated[str, Field(min_length=1, max_length=MAX_KEY_CHARS)]


class PlanSkillContent(_Strict):
    name: str
    version: int
    status: SkillStatus
    sha256: Sha256


class PlanReferentialContent(_Strict):
    name: str
    sha256: Sha256


class PlanContent(_Strict):
    """Contenu canonique haché. Tout champ ajouté change le hash de tous les plans."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Annotated[Literal["foreman.plan/1"], Field(alias="schema")] = PLAN_SCHEMA
    project_id: UUID
    title: Annotated[str, Field(max_length=200)]
    summary: Annotated[str, Field(max_length=500)]
    environment: str
    autonomy_level: Annotated[int, Field(ge=1, le=4)]
    stack: dict[str, str]
    steps: Annotated[list[PlanStepContent], Field(min_length=1, max_length=MAX_STEPS)]
    expected_resources: list[ExpectedResource]
    skills: list[PlanSkillContent]
    referentials: list[PlanReferentialContent]
    policy_sha256: Sha256

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


@dataclass(frozen=True, slots=True)
class DraftStep:
    """Une étape telle que le modèle la propose."""

    title: str
    tool: str | None
    params: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class Draft:
    title: str
    summary: str
    steps: Sequence[DraftStep]
    environment: str | None = None
    stack: Mapping[str, str] | None = None
    skills: Sequence[str] | None = None


# --- Hachage ----------------------------------------------------------------------------------


def canonical_json(value: object) -> bytes:
    """JSON trié, séparateurs compacts, UTF-8 brut ; NaN et infinis refusés."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def content_hash(content: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(content)).hexdigest()


# --- Validation -------------------------------------------------------------------------------


def _walk(value: JsonValue, depth: int = 0) -> list[tuple[int, str]]:
    """Références de `value` (forme validée). Refuse les flottants et l'excès de profondeur."""
    if depth > MAX_DEPTH or isinstance(value, float):
        raise InvalidPlan
    if isinstance(value, dict):
        if REF_KEY in value:
            try:
                return [parse_reference(value)]
            except UnresolvedReference:
                raise InvalidPlan from None
        return [ref for item in value.values() for ref in _walk(item, depth + 1)]
    if isinstance(value, list):
        return [ref for item in value for ref in _walk(item, depth + 1)]
    return []


def _reference_keys(params: Mapping[str, JsonValue]) -> set[str]:
    return {key for key, value in params.items() if _walk(value)}


def _reference_text(value: JsonValue) -> str:
    """Texte d'une valeur dans une clé d'idempotence ; une référence garde sa forme symbolique."""
    if isinstance(value, dict) and is_reference(value):
        step, field = parse_reference(value)
        return f"{REF_KEY}({step}.{field})"
    if isinstance(value, str):
        return value
    return canonical_json(value).decode("utf-8")


def render_key(template: str, project_id: UUID, seq: int, params: Mapping[str, JsonValue]) -> str:
    """Remplace project_id, step_seq et input.x ; laisse `{execution_id}` (approbation)."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "project_id":
            return str(project_id)
        if name == "step_seq":
            return str(seq)
        if name.startswith("input."):
            value = params.get(name[len("input.") :])
            text = "" if value is None else _reference_text(value)
            if "{" in text or "}" in text:
                raise InvalidPlan  # une valeur ne doit pas fabriquer un `{execution_id}`
            return text
        return match.group(0)  # `{execution_id}`

    return _PLACEHOLDER.sub(replace, template)


_NUMERIC: Final = {"integer", "number"}


def _output_types(declared: object) -> set[str]:
    """Types JSON d'un champ de sortie déclaré par le catalogue (`integer`, `{enum: [...]}`...)."""
    if isinstance(declared, str):
        return {declared}
    if isinstance(declared, dict) and isinstance(declared.get("enum"), list):
        return {"string" if isinstance(v, str) else "number" for v in declared["enum"]}
    return {"array"} if isinstance(declared, list) else set()


def _accepts(declared: object, schema: object) -> bool:
    """Le paramètre accepte-t-il une valeur du type de sortie déclaré ? Un paramètre énuméré ou
    sans type n'accepte aucune référence (la valeur ne serait pas garantie)."""
    if not isinstance(schema, dict) or "enum" in schema or "const" in schema:
        return False
    kind = schema.get("type")
    accepted = {kind} if isinstance(kind, str) else set(kind) if isinstance(kind, list) else set()
    produced = _output_types(declared)
    if "number" in accepted:
        accepted |= _NUMERIC
    return bool(produced) and produced <= accepted


def _check_params(
    tool: ToolDefinition,
    params: Mapping[str, JsonValue],
    seq: int,
    earlier: Sequence[ToolDefinition],
) -> None:
    """Références valides et schéma respecté.

    Une référence est la valeur ENTIÈRE d'un paramètre (jamais imbriquée), vise une étape
    antérieure et un champ de sa sortie dont le type convient au paramètre : un refus ici évite
    un échec en cours d'exécution. Le schéma du paramètre n'est pas appliqué à la valeur résolue
    (la gateway le fait à l'exécution) ; les autres paramètres le sont.
    """
    properties = tool.input.get("properties")
    skipped: set[str] = set()
    for key, value in params.items():
        found = _walk(value)
        if not found:
            continue
        if not is_reference(value):
            raise InvalidPlan  # référence imbriquée dans une liste ou un objet
        step, field = found[0]
        if not 1 <= step < seq or field not in earlier[step - 1].output:
            raise InvalidPlan
        schema = properties.get(key) if isinstance(properties, dict) else None
        if not _accepts(earlier[step - 1].output[field], schema):
            raise InvalidPlan
        skipped.add(key)
    problems = [
        error
        for error in Draft202012Validator(tool.input).iter_errors(dict(params))
        if not (error.absolute_path and error.absolute_path[0] in skipped)
    ]
    if problems:
        raise InvalidPlan


def _expected_name(params: Mapping[str, JsonValue], title: str) -> str:
    for key in ("path", "project", "name"):
        value = params.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    return title[:200]


def build_content(draft: Draft, project_id: UUID, catalog: Catalog) -> tuple[PlanContent, str]:
    """Contenu canonique et hash, ou `InvalidPlan`. Pure : rien n'est lu ni écrit.

    Un plan sans `environment` est refusé : l'agent doit le demander (`ask_user`), le serveur ne
    suppose jamais un environnement.
    """
    environment = draft.environment
    matrix = catalog.policy
    if environment is None or environment not in matrix.autonomy.environments or not draft.steps:
        raise InvalidPlan
    steps: list[PlanStepContent] = []
    tools: list[ToolDefinition] = []
    expected: list[ExpectedResource] = []
    for seq, proposed in enumerate(draft.steps, start=1):
        tool = catalog.tools.get(proposed.tool or "")
        if tool is None:
            raise InvalidPlan
        _check_params(tool, proposed.params, seq, tools)
        try:
            reversibility = tool.effective_reversibility(proposed.params)
        except ValueError:
            raise InvalidPlan from None
        template = tool.idempotency.key if tool.idempotency else None
        key = render_key(
            template or f"{EXECUTION_ID_PLACEHOLDER}:{{step_seq}}:{tool.tool}",
            project_id,
            seq,
            proposed.params,
        )
        if _reference_keys(proposed.params) and EXECUTION_ID_PLACEHOLDER not in key:
            # Une clé bâtie sur le texte d'une référence (`$from(1.group_id)`) ne dit rien de la
            # valeur résolue : sans `{execution_id}`, un autre plan du projet le rejouerait.
            key = f"{EXECUTION_ID_PLACEHOLDER}:{key}"
        if not key or len(key) > MAX_KEY_CHARS or reversibility == "per_playbook":
            raise InvalidPlan
        tools.append(tool)
        steps.append(
            PlanStepContent(
                seq=seq,
                title=proposed.title,
                tool=tool.tool,
                tool_version=tool.version,
                tool_class=tool.tool_class,
                reversibility=reversibility,
                params=dict(proposed.params),
                idempotency_key=key,
            )
        )
        if tool.registry is not None:
            expected.append(
                ExpectedResource(
                    provider=tool.connector,
                    resource_type=tool.registry.resource_type,
                    name=_expected_name(proposed.params, proposed.title),
                )
            )
    skills = _skills(draft.skills or (), catalog, environment)
    environments = catalog.referentiels.get("environments")
    configured = environments.data.get("environments") if environments else None
    entry = configured.get(environment) if isinstance(configured, dict) else None
    default_level = entry.get("default_level") if isinstance(entry, dict) else None
    requested = default_level if isinstance(default_level, int) else FALLBACK_LEVEL
    content = PlanContent(
        project_id=project_id,
        title=draft.title,
        summary=draft.summary,
        environment=environment,
        autonomy_level=max(1, effective_level(matrix, environment, requested)),
        stack=dict(draft.stack or {}),
        steps=steps,
        expected_resources=expected,
        skills=skills,
        referentials=[
            PlanReferentialContent(name=ref.name, sha256=ref.sha256)
            for ref in sorted(catalog.referentiels.values(), key=lambda r: r.name)
        ],
        policy_sha256=catalog.policy_sha256,
    )
    canonical = content.canonical()
    if _has_nul(canonical):
        raise InvalidPlan  # PostgreSQL refuse \u0000 : mieux vaut un plan invalide qu'une panne
    try:
        size = len(canonical_json(canonical))
    except ValueError:  # NaN ou infini
        raise InvalidPlan from None
    if size > MAX_PLAN_BYTES:
        raise InvalidPlan
    return content, content_hash(canonical)


def _has_nul(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


def _skills(names: Sequence[str], catalog: Catalog, environment: str) -> list[PlanSkillContent]:
    result: list[PlanSkillContent] = []
    for name in dict.fromkeys(names):  # sans doublon, ordre conservé
        skill = catalog.skills.get(name)
        if skill is None or (
            skill.status == "draft" and environment not in DRAFT_ALLOWED_ENVIRONMENTS
        ):
            raise InvalidPlan  # un Skill en brouillon n'est utilisable qu'en staging
        result.append(
            PlanSkillContent(
                name=skill.name, version=skill.version, status=skill.status, sha256=skill.sha256
            )
        )
    return result


# --- Persistance et carte ---------------------------------------------------------------------


def plan_card(
    record: PlanRecord, content: PlanContent, catalog: Catalog, card_id: str
) -> PlanCardData:
    """Carte plan enrichie. `approvable` : la matrice n'exige pas d'approbation d'administrateur."""
    environment = catalog.policy.autonomy.environments[content.environment]
    return PlanCardData(
        card_id=card_id,
        kind="plan",
        title=content.title,
        summary=content.summary,
        steps=[
            CardStep(
                step=s.seq,
                title=s.title,
                status="pending",
                tool=s.tool,
                tool_class=s.tool_class,
                reversibility=s.reversibility,
            )
            for s in content.steps
        ],
        plan_id=record.id,
        plan_hash=record.content_hash,
        status=record.status,
        environment=content.environment,
        autonomy_level=content.autonomy_level,
        stack=content.stack,
        skills=[SkillRef(name=s.name, version=s.version, sha256=s.sha256) for s in content.skills],
        expected_resources=content.expected_resources,
        approvable=record.status == "proposed" and not environment.admin_approval_required,
    )


def plan_card_id(plan_id: UUID) -> str:
    """Identifiant déterministe : la carte plan réémise à l'approbation remplace la première."""
    return plan_id.hex


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Planner:
    def __init__(
        self, catalog: Catalog, plans: PlanStore, clock: Callable[[], datetime] = _utc_now
    ) -> None:
        self._catalog = catalog
        self._plans = plans
        self._clock = clock

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    async def propose(
        self, project_id: UUID, draft: Draft, requested_by: UUID
    ) -> tuple[PlanRecord, PlanContent]:
        """Valide, hache puis persiste. Un plan invalide n'écrit rien (`InvalidPlan`)."""
        content, digest = build_content(draft, project_id, self._catalog)
        record = await self._plans.create(
            NewPlan(
                project_id=project_id,
                content=content.canonical(),
                content_hash=digest,
                skills_used=[s.model_dump(mode="json") for s in content.skills],
                expires_at=self._clock() + PLAN_TTL,
                requested_by=requested_by,
            )
        )
        return record, content

    def card(self, record: PlanRecord, content: PlanContent) -> PlanCardData:
        return plan_card(record, content, self._catalog, plan_card_id(record.id))
