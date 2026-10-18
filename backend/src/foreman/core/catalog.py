"""Catalogue : outils, Skills, référentiels et matrice de la gateway.

Ce module est pur (aucune lecture de fichier) : il valide des octets déjà lus. Le catalogue est
une donnée de confiance écrite par des humains, mais il est validé comme une entrée : un fichier
invalide fait échouer le démarrage, il n'est jamais corrigé silencieusement. Tout YAML passe par
`yaml.safe_load` (jamais `yaml.load`) : un tag `!!python/object` est rejeté.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal, get_args

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

TOOL_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
REGISTRY_MARKING: Final = "managed-by=foreman"
DRAFT_ALLOWED_ENVIRONMENTS: Final = frozenset({"staging"})
SKILL_SECTIONS: Final = ("# Objectif", "# Instructions", "# Règles", "# Résultat attendu")
MAX_CATALOG_FILE_BYTES: Final = 64 * 1024

# Règles de la matrice connues du code : une règle hors de cette liste est refusée au chargement.
KNOWN_RULE_IDS: Final = frozenset(
    {
        "R1-lecture",
        "R2-controle",
        "R3-niveau4-reprise-et-rollback",
        "R4-remediation-reversible",
        "R5-remediation-autre",
        "R6-ecriture-staging",
        "R7-ecriture-production",
        "R8-irreversible",
        "R9-hors-registre",
        "R10-destructif",
    }
)

ToolClass = Literal["read", "write_registry", "write_foreign", "destructive", "control"]
Reversibility = Literal[
    "reversible", "compensable", "irreversible", "per_playbook", "not_applicable"
]
ScopeKind = Literal["create", "update", "read"]
Decision = Literal["allow", "allow_if"]
Requirement = Literal[
    "plan_approved",
    "admin_approved",
    "remediation_approved_by_admin",
    "adoption_approved_by_admin",
    "command_approved",
]
Purpose = Literal["resume", "rollback_own", "remediation"]
SkillStatus = Literal["draft", "published"]

_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PLACEHOLDER_RE: Final = re.compile(r"\{([^{}]*)\}")
_KEY_VARIABLES: Final = frozenset({"project_id", "execution_id", "step_seq"})
_OBJECT_SCHEMA_CHILD_KEYS: Final = ("properties", "patternProperties", "$defs", "definitions")
_SCHEMA_LIST_KEYS: Final = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCHEMA_SINGLE_KEYS: Final = (
    "items",
    "additionalProperties",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "propertyNames",
)


class CatalogError(Exception):
    """Le catalogue est invalide. Le message nomme la source et la règle, jamais une valeur."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=False)


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# --- Lecture sûre ------------------------------------------------------------------------------


def parse_yaml_mapping(raw: bytes, source: str) -> dict[str, Any]:
    """Décode du YAML avec `safe_load` et exige un objet à la racine."""
    if len(raw) > MAX_CATALOG_FILE_BYTES:
        raise CatalogError(f"{source}: fichier trop volumineux")
    try:
        loaded = yaml.safe_load(raw.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CatalogError(f"{source}: YAML invalide ou non sûr") from exc
    if not isinstance(loaded, dict) or not all(isinstance(k, str) for k in loaded):
        raise CatalogError(f"{source}: un objet YAML est attendu à la racine")
    return loaded


def _validate[M: BaseModel](model: type[M], data: Mapping[str, Any], source: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<racine>'}: {e['msg']}" for e in exc.errors()
        )
        raise CatalogError(f"{source}: {problems}") from exc


# --- Outils ------------------------------------------------------------------------------------


def _is_object_schema(node: Mapping[str, Any]) -> bool:
    kind = node.get("type")
    is_typed = kind == "object" or (isinstance(kind, list) and "object" in kind)
    return is_typed or "properties" in node or "patternProperties" in node


def _subschemas(node: Mapping[str, Any]) -> Iterable[tuple[str, Any]]:
    for key in _OBJECT_SCHEMA_CHILD_KEYS:
        children = node.get(key)
        if isinstance(children, dict):
            for name, child in children.items():
                yield f"{key}.{name}", child
    for key in _SCHEMA_LIST_KEYS:
        children = node.get(key)
        if isinstance(children, list):
            for i, child in enumerate(children):
                yield f"{key}[{i}]", child
    for key in _SCHEMA_SINGLE_KEYS:
        child = node.get(key)
        if isinstance(child, dict):
            yield key, child
        elif key == "items" and isinstance(child, list):
            for i, item in enumerate(child):
                yield f"items[{i}]", item


def schema_problems(schema: Mapping[str, Any], path: str = "input") -> list[str]:
    """Défauts de fermeture : `additionalProperties: false` à TOUS les niveaux d'objet."""
    problems: list[str] = []
    if "$ref" in schema or "$dynamicRef" in schema:
        problems.append(f"{path}: les références ($ref) ne sont pas prises en charge")
    if _is_object_schema(schema) and schema.get("additionalProperties") is not False:
        problems.append(f"{path}: additionalProperties doit valoir false")
    for sub_path, child in _subschemas(schema):
        if isinstance(child, dict):
            problems.extend(schema_problems(child, f"{path}.{sub_path}"))
    return problems


class Idempotency(_Strict):
    key: Annotated[str, Field(min_length=1, max_length=300)]
    strategy: Literal["lookup_then_create"] | None = None
    on_conflict: Literal["return_previous_result"] | None = None

    @model_validator(mode="after")
    def _exactly_one_policy(self) -> "Idempotency":
        if (self.strategy is None) == (self.on_conflict is None):
            raise ValueError("exactement un de strategy et on_conflict est requis")
        return self


class RegistryEntry(_Strict):
    resource_type: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    external_id: Annotated[str, Field(min_length=1)]
    marking: Annotated[str, Field(min_length=1)]

    @field_validator("marking")
    @classmethod
    def _marking_names_foreman(cls, value: str) -> str:
        if REGISTRY_MARKING not in value:
            raise ValueError(f"le marquage doit contenir {REGISTRY_MARKING}")
        return value


class Scope(_Strict):
    kind: ScopeKind
    target: str | None = None
    parent: str | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Scope":
        if self.kind == "create" and (self.parent is None or self.target is not None):
            raise ValueError("create exige parent (et pas target)")
        if self.kind == "update" and (self.target is None or self.parent is not None):
            raise ValueError("update exige target (et pas parent)")
        if self.kind == "read" and (self.target is not None or self.parent is not None):
            raise ValueError("read n'a ni target ni parent")
        return self


class ToolDefinition(_Strict):
    """Définition d'un outil. La classe et la réversibilité viennent d'ici, jamais du modèle."""

    tool: Annotated[str, Field(pattern=TOOL_NAME_PATTERN)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    tool_class: Annotated[ToolClass, Field(alias="class")]
    reversibility: Reversibility
    connector: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    idempotency: Idempotency | None = None
    registry: RegistryEntry | None = None
    scope: Scope
    redact: list[str] = Field(default_factory=list)
    timeout_s: Annotated[int, Field(gt=0, le=900)]

    @property
    def name(self) -> str:
        return self.tool

    @model_validator(mode="after")
    def _consistent(self) -> "ToolDefinition":
        if not self.tool.startswith(f"{self.connector}."):
            raise ValueError("le nom de l'outil doit commencer par son connecteur")
        problems = self._input_problems()
        if problems:
            raise ValueError("; ".join(problems))
        is_write = self.tool_class in ("write_registry", "write_foreign", "destructive")
        if self.tool_class in ("read", "control") and self.reversibility != "not_applicable":
            raise ValueError("un outil de lecture ou de contrôle est not_applicable")
        if self.tool_class == "write_registry" and self.reversibility == "not_applicable":
            raise ValueError("un outil d'écriture déclare sa réversibilité")
        if is_write and self.idempotency is None:
            raise ValueError("un outil d'écriture déclare son idempotence")
        if self.tool_class == "write_registry" and self.registry is None:
            raise ValueError("un outil write_registry déclare son entrée de registre")
        if self.tool_class == "write_registry" and self.scope.kind == "read":
            raise ValueError("un outil d'écriture n'a pas une portée read")
        if self.tool_class in ("read", "control") and self.scope.kind != "read":
            raise ValueError("un outil de lecture ou de contrôle a une portée read")
        if self.registry is not None and self.registry.external_id not in self.output:
            raise ValueError("registry.external_id doit être un champ de output")
        properties = self.input.get("properties")
        names = set(properties) if isinstance(properties, dict) else set()
        for ref in (self.scope.parent, self.scope.target):
            if ref is not None and ref not in names:
                raise ValueError("scope fait référence à un paramètre inconnu")
        if self.idempotency is not None:
            self._check_key(self.idempotency.key, names)
        return self

    def _input_problems(self) -> list[str]:
        try:
            Draft202012Validator.check_schema(self.input)
        except SchemaError:
            return ["input: schéma JSON invalide"]
        problems = schema_problems(self.input)
        if self.input.get("type") != "object":
            problems.append("input: la racine doit être de type object")
        return problems

    @staticmethod
    def _check_key(key: str, input_names: set[str]) -> None:
        for placeholder in _PLACEHOLDER_RE.findall(key):
            if placeholder in _KEY_VARIABLES:
                continue
            if placeholder.startswith("input.") and placeholder[len("input.") :] in input_names:
                continue
            raise ValueError("idempotency.key: variable inconnue")


def parse_tool(raw: bytes, source: str) -> ToolDefinition:
    data = parse_yaml_mapping(raw, source)
    if "class" not in data or "reversibility" not in data:
        raise CatalogError(f"{source}: class et reversibility sont obligatoires")
    return _validate(ToolDefinition, data, source)


# --- Skills ------------------------------------------------------------------------------------


class SkillDocument(_Strict):
    """Un `SKILL.md`. `sha256` couvre les octets exacts du fichier : un octet change le hash."""

    name: Annotated[str, Field(pattern=_NAME_RE.pattern)]
    version: Annotated[int, Field(ge=1, strict=True)]
    status: SkillStatus
    description: Annotated[str, Field(min_length=1, max_length=500)]
    tools: list[Annotated[str, Field(pattern=TOOL_NAME_PATTERN)]]
    body: Annotated[str, Field(min_length=1)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @field_validator("body")
    @classmethod
    def _has_sections(cls, value: str) -> str:
        lines = {line.strip() for line in value.splitlines()}
        missing = [s for s in SKILL_SECTIONS if s not in lines]
        if missing:
            raise ValueError(f"sections manquantes : {', '.join(missing)}")
        return value


class _SkillFrontMatter(_Strict):
    name: str
    version: Annotated[int, Field(strict=True)]
    status: SkillStatus
    description: str
    tools: list[str]


def parse_skill(raw: bytes, source: str, expected_name: str | None = None) -> SkillDocument:
    if len(raw) > MAX_CATALOG_FILE_BYTES:
        raise CatalogError(f"{source}: fichier trop volumineux")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CatalogError(f"{source}: encodage UTF-8 attendu") from exc
    opening = "---\n"
    if not text.startswith(opening):
        raise CatalogError(f"{source}: front matter manquant")
    end = text.find("\n---\n", len(opening) - 1)
    if end == -1:
        raise CatalogError(f"{source}: front matter non terminé")
    front_raw = text[len(opening) : end + 1]
    body = text[end + len("\n---\n") :]
    front = parse_yaml_mapping(front_raw.encode("utf-8"), f"{source} (front matter)")
    meta = _validate(_SkillFrontMatter, front, source)
    if expected_name is not None and meta.name != expected_name:
        raise CatalogError(f"{source}: le nom du Skill doit être celui de son dossier")
    return _validate(
        SkillDocument,
        {**meta.model_dump(), "body": body, "sha256": sha256_hex(raw)},
        source,
    )


# --- Référentiels ------------------------------------------------------------------------------


class Referentiel(_Strict):
    """Faits d'infrastructure (YAML). Le contenu est libre, le hash le trace."""

    name: Annotated[str, Field(pattern=_NAME_RE.pattern)]
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    data: dict[str, JsonValue] = Field(min_length=1)


def parse_referentiel(raw: bytes, name: str, source: str) -> Referentiel:
    data = parse_yaml_mapping(raw, source)
    return _validate(Referentiel, {"name": name, "sha256": sha256_hex(raw), "data": data}, source)


# --- Matrice -----------------------------------------------------------------------------------


def _as_list(value: object) -> object:
    return value if value is None or isinstance(value, list) else [value]


class RuleMatch(_Strict):
    tool_class: Annotated[ToolClass | None, Field(alias="class")] = None
    env: list[str] | None = None
    purpose: list[Purpose] | None = None
    reversibility: list[Reversibility] | None = None

    @field_validator("env", "purpose", "reversibility", mode="before")
    @classmethod
    def _wrap(cls, value: object) -> object:
        return _as_list(value)


class Rule(_Strict):
    id: str
    match: RuleMatch
    roles: list[str] | None = None
    min_level: Annotated[int, Field(ge=1, le=4)] | None = None
    requires: list[Requirement] = Field(default_factory=list)
    decision: Decision
    never_autonomous: bool = False

    @field_validator("id")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in KNOWN_RULE_IDS:
            raise ValueError("règle de matrice inconnue")
        return value

    @model_validator(mode="after")
    def _requires_follow_decision(self) -> "Rule":
        if self.decision == "allow" and self.requires:
            raise ValueError("allow n'a pas de requires (utiliser allow_if)")
        if self.decision == "allow_if" and not self.requires:
            raise ValueError("allow_if exige au moins un requires")
        return self


class EnvironmentAutonomy(_Strict):
    max_level: Annotated[int, Field(ge=1, le=4)]
    admin_approval_required: bool


class Autonomy(_Strict):
    org_ceiling: Annotated[int, Field(ge=1, le=4)]
    environments: dict[str, EnvironmentAutonomy] = Field(min_length=1)


class ExecutionBudget(_Strict):
    max_tool_calls: Annotated[int, Field(gt=0)]
    max_minutes: Annotated[int, Field(gt=0)]
    max_retries_per_step: Annotated[int, Field(ge=0)]
    max_model_cost_eur: Annotated[float, Field(ge=0)]


class Budgets(_Strict):
    per_execution: ExecutionBudget


class PolicyMatrix(_Strict):
    """Matrice de la gateway. Ici : chargement et validation, l'évaluation est ailleurs."""

    version: Literal[1]
    default: Literal["deny"]
    roles: Annotated[list[str], Field(min_length=1)]
    autonomy: Autonomy
    classes: dict[str, str]
    budgets: Budgets
    rules: Annotated[list[Rule], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistent(self) -> "PolicyMatrix":
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("identifiant de règle en double")
        if set(self.classes) != set(get_args(ToolClass)):
            raise ValueError("classes : les cinq classes d'outils sont attendues")
        for rule in self.rules:
            if rule.roles is not None and not set(rule.roles) <= set(self.roles):
                raise ValueError("règle avec un rôle inconnu")
        return self


def parse_policy(raw: bytes, source: str) -> PolicyMatrix:
    return _validate(PolicyMatrix, parse_yaml_mapping(raw, source), source)


# --- Assemblage --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Catalog:
    tools: Mapping[str, ToolDefinition]
    skills: Mapping[str, SkillDocument]
    referentiels: Mapping[str, Referentiel]
    policy: PolicyMatrix
    policy_sha256: str


def build_catalog(
    *,
    tools: Iterable[ToolDefinition],
    skills: Iterable[SkillDocument],
    referentiels: Iterable[Referentiel],
    policy: PolicyMatrix,
    policy_sha256: str,
    environment: str,
) -> Catalog:
    """Assemble le catalogue et applique les règles transverses.

    Un Skill `draft` n'est utilisable qu'en staging ; un Skill ne cite que des outils connus.
    """
    tool_map: dict[str, ToolDefinition] = {}
    for tool in tools:
        if tool.tool in tool_map:
            raise CatalogError(f"outil en double : {tool.tool}")
        tool_map[tool.tool] = tool
    skill_map: dict[str, SkillDocument] = {}
    for skill in skills:
        if skill.name in skill_map:
            raise CatalogError(f"Skill en double : {skill.name}")
        if skill.status == "draft" and environment not in DRAFT_ALLOWED_ENVIRONMENTS:
            raise CatalogError(f"Skill {skill.name} en brouillon : refusé hors staging")
        unknown = [t for t in skill.tools if t not in tool_map]
        if unknown:
            raise CatalogError(f"Skill {skill.name} cite des outils inconnus : {unknown}")
        skill_map[skill.name] = skill
    ref_map: dict[str, Referentiel] = {}
    for ref in referentiels:
        if ref.name in ref_map:
            raise CatalogError(f"référentiel en double : {ref.name}")
        ref_map[ref.name] = ref
    return Catalog(tool_map, skill_map, ref_map, policy, policy_sha256)
