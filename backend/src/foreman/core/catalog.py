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

from foreman.core.events import Requirement, Sha256

TOOL_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
REGISTRY_MARKING: Final = "managed-by=foreman"
DRAFT_ALLOWED_ENVIRONMENTS: Final = frozenset({"staging"})
SKILL_SECTIONS: Final = ("# Objectif", "# Instructions", "# Règles", "# Résultat attendu")
MAX_CATALOG_FILE_BYTES: Final = 64 * 1024
MAX_PRODUCTION_LEVEL: Final = 3  # la production n'est jamais pleinement autonome (niveau 4)


ToolClass = Literal["read", "write_registry", "write_foreign", "destructive", "control"]
Reversibility = Literal[
    "reversible", "compensable", "irreversible", "per_playbook", "not_applicable"
]
ScopeKind = Literal["create", "update", "read"]
Decision = Literal["allow", "allow_if"]
Purpose = Literal["resume", "rollback_own", "remediation"]
SkillStatus = Literal["draft", "published"]

_NAME_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PLACEHOLDER_RE: Final = re.compile(r"\{([^{}]*)\}")
_TEMPLATE_RE: Final = re.compile(r"(\{input\.[a-z_]+\}|[^{}])+")
_KEY_VARIABLES: Final = frozenset({"project_id", "execution_id", "step_seq"})
# Liste blanche des mots-clés JSON Schema : tout le reste (patternProperties, unevaluated*,
# dependentSchemas, not, if/then/else, $ref, prefixItems...) est refusé, donc ne peut pas contourner
# la fermeture des objets.
_ALLOWED_KEYWORDS: Final = frozenset(
    {
        "type", "enum", "const", "properties", "required", "additionalProperties", "items",
        "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "format",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "minProperties", "maxProperties", "allOf", "anyOf", "oneOf", "description", "title",
        "default", "examples",
    }
)  # fmt: skip
_COMBINATORS: Final = ("allOf", "anyOf", "oneOf")
# Règles connues du code, avec la classe (et l'environnement) qu'elles visent : une règle hors de
# cette table, ou détournée vers une autre classe, est refusée au chargement.
RULE_BINDINGS: Final[Mapping[str, tuple[str, str | None]]] = {
    "R1-lecture": ("read", None),
    "R2-controle": ("control", None),
    "R3-niveau4-reprise-et-rollback": ("write_registry", "staging"),
    "R4-remediation-reversible": ("write_registry", None),
    "R5-remediation-autre": ("write_registry", None),
    "R6-ecriture-staging": ("write_registry", "staging"),
    "R7-ecriture-production": ("write_registry", "production"),
    "R8-irreversible": ("write_registry", None),
    "R9-hors-registre": ("write_foreign", None),
    "R10-destructif": ("destructive", None),
}


class CatalogError(Exception):
    """Le catalogue est invalide. Le message nomme la source et la règle, jamais une valeur."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=False)


def sha256_ref(raw: bytes) -> str:
    """Empreinte au format du contrat (`events.Sha256`) : `sha256:<64 hex>`."""
    return "sha256:" + hashlib.sha256(raw).hexdigest()


# --- Lecture sûre ------------------------------------------------------------------------------


def check_text_bytes(raw: bytes, source: str) -> str:
    """Texte UTF-8 en LF, sans BOM : sinon le hash dépendrait du poste de travail."""
    if len(raw) > MAX_CATALOG_FILE_BYTES:
        raise CatalogError(f"{source}: fichier trop volumineux")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CatalogError(f"{source}: BOM UTF-8 interdit")
    if b"\r" in raw:
        raise CatalogError(f"{source}: fins de ligne CRLF interdites (LF attendu)")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CatalogError(f"{source}: encodage UTF-8 attendu") from None


def parse_yaml_mapping(raw: bytes, source: str) -> dict[str, Any]:
    """Décode du YAML avec `safe_load` et exige un objet à la racine."""
    text = check_text_bytes(raw, source)
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError:
        # `from None` : la cause YAML cite un extrait du fichier, qui ne doit sortir nulle part.
        raise CatalogError(f"{source}: YAML invalide ou non sûr") from None
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
        # `from None` : la cause pydantic porte les valeurs invalides.
        raise CatalogError(f"{source}: {problems}") from None


# --- Outils ------------------------------------------------------------------------------------


def schema_problems(schema: object, path: str = "input") -> list[str]:
    """Défauts de fermeture d'un schéma d'entrée, à TOUS les niveaux.

    Chaque sous-schéma est un objet (pas de schéma booléen), n'utilise que des mots-clés de la
    liste blanche, déclare un `type` (ou `enum`/`const`), ferme ses objets par
    `additionalProperties: false` et déclare les `items` de ses tableaux.
    """
    if not isinstance(schema, dict):
        return [f"{path}: un schéma objet est attendu (pas de schéma booléen)"]
    problems: list[str] = []
    unknown = sorted(set(schema) - _ALLOWED_KEYWORDS)
    if unknown:
        problems.append(f"{path}: mots-clés non pris en charge : {unknown}")
    kind = schema.get("type")
    if isinstance(kind, str):
        types = [kind]
    elif isinstance(kind, list) and all(isinstance(t, str) for t in kind):
        types = list(kind)
    else:
        types = []
        if kind is not None:
            problems.append(f"{path}: type invalide")
    if kind is None and not any(k in schema for k in ("enum", "const", *_COMBINATORS)):
        problems.append(f"{path}: type, enum, const ou combinaison explicite requis")
    if ("properties" in schema or "required" in schema) and "object" not in types:
        problems.append(f"{path}: properties ou required exigent type object")
    if "object" in types and schema.get("additionalProperties") is not False:
        problems.append(f"{path}: additionalProperties doit valoir false")
    if "array" in types and not isinstance(schema.get("items"), dict):
        problems.append(f"{path}: un tableau déclare ses items")
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, child in properties.items():
            problems.extend(schema_problems(child, f"{path}.{name}"))
    elif properties is not None:
        problems.append(f"{path}: properties doit être un objet")
    if "items" in schema:
        problems.extend(schema_problems(schema["items"], f"{path}[]"))
    for key in _COMBINATORS:
        branches = schema.get(key)
        if isinstance(branches, list):
            for i, child in enumerate(branches):
                problems.extend(schema_problems(child, f"{path}.{key}[{i}]"))
        elif branches is not None:
            problems.append(f"{path}: {key} doit être une liste")
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
    external_id: Annotated[
        str, Field(min_length=1)
    ]  # un champ, ou un gabarit "{input.x}/{input.y}"
    marking: Annotated[str, Field(min_length=1)]

    def identify(self, params: Mapping[str, Any], output: Mapping[str, Any] | None = None) -> Any:
        """Valeur brute de l'identifiant (sortie puis paramètres), ou `None` si un champ manque.

        Un gabarit n'utilise que des paramètres d'entrée : il est composé en texte.
        """
        if "{" not in self.external_id:
            return (output or {}).get(self.external_id, params.get(self.external_id))
        parts = [
            params.get(name[len("input.") :]) for name in _PLACEHOLDER_RE.findall(self.external_id)
        ]
        if any(isinstance(v, bool) or not isinstance(v, int | str) or v == "" for v in parts):
            return None
        return _PLACEHOLDER_RE.sub(
            lambda m: str(params[m.group(1)[len("input.") :]]), self.external_id
        )

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


class PlaybookDefinition(_Strict):
    """Réversibilité et portée d'UN playbook, lues par la gateway avant la matrice."""

    reversibility: Literal["reversible", "compensable", "irreversible"]
    scope: Scope


class ToolDefinition(_Strict):
    """Définition d'un outil. La classe et la réversibilité viennent d'ici, jamais du modèle.

    Un outil `per_playbook` déclare `playbooks` (une entrée par valeur du paramètre `playbook`) ;
    la réversibilité et la portée effectives sont celles du playbook appelé
    (`effective_reversibility`, `effective_scope`). La gateway doit aussi imposer que
    `params.environment` soit celui du plan : le schéma seul ne le garantit pas.
    """

    tool: Annotated[str, Field(pattern=TOOL_NAME_PATTERN)]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    tool_class: Annotated[ToolClass, Field(alias="class")]
    reversibility: Reversibility
    connector: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    input: dict[str, JsonValue]
    output: dict[str, JsonValue]
    idempotency: Idempotency | None = None
    registry: RegistryEntry | None = None
    scope: Scope | None = None
    playbooks: dict[str, PlaybookDefinition] | None = None
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
        properties = self.input.get("properties")
        names = set(properties) if isinstance(properties, dict) else set()
        self._check_class(names)
        self._check_scopes(names)
        if self.registry is not None:
            external_id = self.registry.external_id
            if "{" in external_id:
                wanted = _PLACEHOLDER_RE.findall(external_id)
                known = all(w[len("input.") :] in names for w in wanted)
                if not (_TEMPLATE_RE.fullmatch(external_id) and known):
                    raise ValueError("registry.external_id: gabarit limité aux champs {input.x}")
            elif external_id not in names | set(self.output):
                raise ValueError("registry.external_id doit être un champ de input ou de output")
        if self.idempotency is not None:
            self._check_key(self.idempotency.key, names)
        return self

    def _check_class(self, names: set[str]) -> None:
        is_write = self.tool_class in ("write_registry", "write_foreign", "destructive")
        if self.tool_class in ("read", "control") and self.reversibility != "not_applicable":
            raise ValueError("un outil de lecture ou de contrôle est not_applicable")
        if self.tool_class == "write_registry" and self.reversibility == "not_applicable":
            raise ValueError("un outil d'écriture déclare sa réversibilité")
        if is_write and self.idempotency is None:
            raise ValueError("un outil d'écriture déclare son idempotence")
        if self.tool_class == "write_registry" and self.registry is None:
            raise ValueError("un outil write_registry déclare son entrée de registre")
        if self.reversibility == "per_playbook":
            self._check_playbooks()
        elif self.playbooks is not None:
            raise ValueError("playbooks n'est admis que pour per_playbook")

    def _check_playbooks(self) -> None:
        properties = self.input.get("properties")
        playbook = properties.get("playbook") if isinstance(properties, dict) else None
        allowed = playbook.get("enum") if isinstance(playbook, dict) else None
        if not self.playbooks or not isinstance(allowed, list):
            raise ValueError("per_playbook exige playbooks et un enum input.playbook")
        if set(self.playbooks) != set(allowed):
            raise ValueError("playbooks doit couvrir exactement l'enum input.playbook")
        if self.scope is not None:
            raise ValueError("per_playbook : la portée est déclarée par playbook")
        if self.tool_class != "write_registry":
            raise ValueError("per_playbook concerne un outil write_registry")

    def _check_scopes(self, names: set[str]) -> None:
        scopes = [d.scope for d in (self.playbooks or {}).values()]
        if self.scope is not None:
            scopes.append(self.scope)
        elif self.playbooks is None:
            raise ValueError("la portée (scope) est obligatoire")
        for scope in scopes:
            for ref in (scope.parent, scope.target):
                if ref is not None and ref not in names:
                    raise ValueError("scope fait référence à un paramètre inconnu")
            if self.tool_class == "write_registry" and scope.kind == "read":
                raise ValueError("un outil d'écriture n'a pas une portée read")
            if self.tool_class in ("read", "control") and scope.kind != "read":
                raise ValueError("un outil de lecture ou de contrôle a une portée read")

    def effective_reversibility(self, params: Mapping[str, Any]) -> Reversibility:
        """Réversibilité de l'appel : celle du playbook pour un outil `per_playbook`."""
        if self.playbooks is None:
            return self.reversibility
        return self._playbook(params).reversibility

    def effective_scope(self, params: Mapping[str, Any]) -> Scope:
        if self.playbooks is None:
            if self.scope is None:  # exclu par le chargeur
                raise ValueError("portée absente")
            return self.scope
        return self._playbook(params).scope

    def _playbook(self, params: Mapping[str, Any]) -> PlaybookDefinition:
        definition = (self.playbooks or {}).get(str(params.get("playbook")))
        if definition is None:
            raise ValueError("playbook inconnu")
        return definition

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
    sha256: Sha256

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
    text = check_text_bytes(raw, source)
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
        {**meta.model_dump(), "body": body, "sha256": sha256_ref(raw)},
        source,
    )


# --- Référentiels ------------------------------------------------------------------------------


class Referentiel(_Strict):
    """Faits d'infrastructure (YAML). Le contenu est libre, le hash le trace."""

    name: Annotated[str, Field(pattern=_NAME_RE.pattern)]
    sha256: Sha256
    data: dict[str, JsonValue] = Field(min_length=1)


def parse_referentiel(raw: bytes, name: str, source: str) -> Referentiel:
    data = parse_yaml_mapping(raw, source)
    return _validate(Referentiel, {"name": name, "sha256": sha256_ref(raw), "data": data}, source)


# --- Matrice -----------------------------------------------------------------------------------


def _as_list(value: object) -> object:
    return value if value is None or isinstance(value, list) else [value]


class RuleMatch(_Strict):
    tool_class: Annotated[ToolClass, Field(alias="class")]
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
        if value not in RULE_BINDINGS:
            raise ValueError("règle de matrice inconnue")
        return value

    @model_validator(mode="after")
    def _requires_follow_decision(self) -> "Rule":
        if self.decision == "allow" and self.requires:
            raise ValueError("allow n'a pas de requires (utiliser allow_if)")
        if self.decision == "allow_if" and not self.requires:
            raise ValueError("allow_if exige au moins un requires")
        tool_class = self.match.tool_class
        if tool_class in ("write_registry", "write_foreign", "destructive"):
            if self.decision != "allow_if":
                raise ValueError("une écriture n'est jamais allow : allow_if avec exigences")
            if tool_class == "write_registry" and "plan_approved" not in self.requires:
                raise ValueError("une écriture dans le registre exige plan_approved")
        if self.never_autonomous and (
            self.decision != "allow_if" or "admin_approved" not in self.requires
        ):
            raise ValueError("never_autonomous exige allow_if avec admin_approved")
        if tool_class == "destructive" and (
            "admin_approved" not in self.requires or not self.never_autonomous
        ):
            raise ValueError("une règle destructive exige admin_approved et never_autonomous")
        bound_class, bound_env = RULE_BINDINGS[self.id]
        if tool_class != bound_class:
            raise ValueError(f"la règle {self.id} porte sur la classe {bound_class}")
        if bound_env is not None and self.match.env != [bound_env]:
            raise ValueError(f"la règle {self.id} porte sur l'environnement {bound_env}")
        return self


class EnvironmentAutonomy(_Strict):
    max_level: Annotated[int, Field(ge=1, le=4)]
    admin_approval_required: bool


class Approvers(_Strict):
    """Rôles autorisés à donner chaque approbation : le front lit cette liste."""

    developer: Annotated[list[str], Field(min_length=1)]
    admin: Annotated[list[str], Field(min_length=1)]


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
    approvers: Approvers
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
        if not set(self.approvers.developer + self.approvers.admin) <= set(self.roles):
            raise ValueError("approvers : rôle inconnu")
        production = self.autonomy.environments.get("production")
        if production is not None and production.max_level > MAX_PRODUCTION_LEVEL:
            raise ValueError("production : max_level supérieur à 3 refusé")
        for rule in self.rules:
            unknown_env = set(rule.match.env or []) - set(self.autonomy.environments)
            if unknown_env:
                raise ValueError("règle sur un environnement absent de autonomy.environments")
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
