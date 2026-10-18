"""Catalogue : chargement, refus (un test par règle) et traçabilité des Skills par hash."""

import copy
import hashlib
import os
import shutil
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from foreman.bootstrap.configure import Profile, configure
from foreman.core.catalog import (
    REGISTRY_MARKING,
    Catalog,
    CatalogError,
    parse_policy,
    parse_referentiel,
    parse_skill,
    parse_tool,
    parse_yaml_mapping,
    schema_problems,
)
from foreman.core.events import SkillRef
from foreman.infra.file_catalog import DEFAULT_TOOLS_ROOT, load_catalog, read_catalog_file

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "catalog"

# Outil -> (classe, réversibilité) : la classe vient du catalogue, jamais du modèle.
S1_TOOLS = {
    "gitlab.create_group": ("write_registry", "compensable"),
    "gitlab.create_project": ("write_registry", "compensable"),
    "server.apply_playbook": ("write_registry", "per_playbook"),
    "server.healthcheck": ("read", "not_applicable"),
    "dns.list_records": ("read", "not_applicable"),
}
S1_SKILLS = {"gitlab-project-creation", "go-backend-standard", "docker-staging-deploy"}
UNSAFE_YAML = "x: !!python/object/apply:pathlib.Path ['/tmp/foreman-unsafe']\n"


def dump(data: object) -> bytes:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).encode("utf-8")


def tool_source(name: str) -> dict[str, Any]:
    connector, short = name.split(".")
    path = DEFAULT_TOOLS_ROOT / connector / "tools" / f"{short}.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.fixture
def workdir(tmp_path: Path) -> tuple[Path, Path]:
    """Copie modifiable du catalogue et des définitions d'outils."""
    catalog = tmp_path / "catalog"
    tools = tmp_path / "integrations"
    shutil.copytree(CATALOG_DIR, catalog)
    shutil.copytree(DEFAULT_TOOLS_ROOT, tools, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    return catalog, tools


def load(workdir: tuple[Path, Path], environment: str = "staging") -> Catalog:
    catalog, tools = workdir
    return load_catalog(catalog, environment=environment, tools_root=tools)


# --- Le catalogue livré se charge --------------------------------------------------------------


def test_the_shipped_catalog_loads_every_s1_tool_skill_and_referentiel() -> None:
    catalog = load_catalog(CATALOG_DIR, environment="staging")
    assert {n: (t.tool_class, t.reversibility) for n, t in catalog.tools.items()} == S1_TOOLS
    assert set(catalog.skills) == S1_SKILLS
    assert set(catalog.referentiels) == {
        "gitlab-groups",
        "infra-staging",
        "environments",
        "boilerplates",
        "project-schema",
    }
    for tool in catalog.tools.values():
        if tool.tool_class == "write_registry":
            assert tool.registry is not None
            assert REGISTRY_MARKING in tool.registry.marking
            assert tool.idempotency is not None


def test_the_matrix_loads_with_default_deny_and_the_minimal_rules() -> None:
    policy = load_catalog(CATALOG_DIR, environment="staging").policy
    assert policy.default == "deny"
    assert [r.id for r in policy.rules] == ["R1-lecture", "R2-controle", "R6-ecriture-staging"]
    r6 = policy.rules[2]
    assert r6.requires == ["plan_approved"]
    assert r6.min_level == 2
    assert policy.budgets.per_execution.max_tool_calls == 60
    assert policy.budgets.per_execution.max_minutes == 30
    assert policy.autonomy.environments["staging"].max_level == 4


def test_the_referentiels_hold_the_fictitious_s1_facts() -> None:
    refs = load_catalog(CATALOG_DIR, environment="staging").referentiels
    assert refs["gitlab-groups"].data["root_group"] == {
        "id": 1000,
        "path": "foreman-demo",
        "web_url": "https://gitlab.example.org/foreman-demo",
    }
    assert refs["infra-staging"].data["dns"] == {
        "wildcard": "*.staging.example.org",
        "managed_externally": True,
        "points_to": "server-staging-1",
    }
    assert refs["environments"].data["environments"] == {
        "staging": {"max_level": 4, "admin_approval_required": False, "default_level": 2}
    }


# --- Outils : un test par règle de refus ---------------------------------------------------------


def _drop_root_closure(d: dict[str, Any]) -> None:
    del d["input"]["additionalProperties"]


def _open_root_closure(d: dict[str, Any]) -> None:
    d["input"]["additionalProperties"] = True


def _drop_nested_closure(d: dict[str, Any]) -> None:
    del d["input"]["properties"]["extra_vars"]["additionalProperties"]


def _drop_class(d: dict[str, Any]) -> None:
    del d["class"]


def _drop_reversibility(d: dict[str, Any]) -> None:
    del d["reversibility"]


def _unknown_class(d: dict[str, Any]) -> None:
    d["class"] = "write_everything"


def _drop_idempotency(d: dict[str, Any]) -> None:
    del d["idempotency"]


def _unmarked_registry(d: dict[str, Any]) -> None:
    d["registry"]["marking"] = "mention managed-by=devplatform"


def _scope_to_unknown_parameter(d: dict[str, Any]) -> None:
    d["scope"] = {"kind": "create", "parent": "no_such_parameter"}


def _idempotency_key_with_unknown_variable(d: dict[str, Any]) -> None:
    d["idempotency"]["key"] = "{input.no_such_parameter}"


def _unknown_field(d: dict[str, Any]) -> None:
    d["shell"] = "rm -rf /"


@pytest.mark.parametrize(
    ("tool", "mutate"),
    [
        pytest.param("server.apply_playbook", _drop_root_closure, id="no-additionalProperties"),
        pytest.param("server.apply_playbook", _open_root_closure, id="additionalProperties-true"),
        pytest.param("server.apply_playbook", _drop_nested_closure, id="nested-object-not-closed"),
        pytest.param("gitlab.create_group", _drop_class, id="no-class"),
        pytest.param("dns.list_records", _drop_reversibility, id="no-reversibility"),
        pytest.param("gitlab.create_group", _unknown_class, id="unknown-class"),
        pytest.param("gitlab.create_group", _drop_idempotency, id="write-without-idempotency"),
        pytest.param("gitlab.create_group", _unmarked_registry, id="registry-not-foreman"),
        pytest.param("gitlab.create_group", _scope_to_unknown_parameter, id="scope-unknown-param"),
        pytest.param("gitlab.create_group", _idempotency_key_with_unknown_variable, id="bad-key"),
        pytest.param("gitlab.create_group", _unknown_field, id="unknown-field"),
    ],
)
def test_a_tool_definition_breaking_a_rule_is_refused(
    tool: str, mutate: Callable[[dict[str, Any]], None]
) -> None:
    source = copy.deepcopy(tool_source(tool))
    parse_tool(dump(source), tool)  # la définition de départ est valide
    mutate(source)
    with pytest.raises(CatalogError):
        parse_tool(dump(source), tool)


def test_a_tool_whose_name_does_not_follow_its_location_is_refused(
    workdir: tuple[Path, Path],
) -> None:
    _, tools = workdir
    (tools / "dns" / "tools" / "list_records.yaml").rename(tools / "dns" / "tools" / "other.yaml")
    with pytest.raises(CatalogError):
        load(workdir)


def test_a_tool_with_a_ref_in_its_schema_is_refused() -> None:
    source = copy.deepcopy(tool_source("server.healthcheck"))
    source["input"]["properties"]["project"] = {"$ref": "http://169.254.169.254/schema"}
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "server.healthcheck")


def test_an_array_of_objects_must_also_be_closed() -> None:
    source = copy.deepcopy(tool_source("server.healthcheck"))
    source["input"]["properties"]["targets"] = {
        "type": "array",
        "items": {"type": "object", "properties": {"host": {"type": "string"}}},
    }
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "server.healthcheck")
    source["input"]["properties"]["targets"]["items"]["additionalProperties"] = False
    parse_tool(dump(source), "server.healthcheck")


# --- Matrice -----------------------------------------------------------------------------------


def policy_source() -> dict[str, Any]:
    loaded = yaml.safe_load((CATALOG_DIR / "policy" / "matrix.yaml").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _unknown_rule(d: dict[str, Any]) -> None:
    d["rules"].append({"id": "R99-tout-permettre", "match": {"class": "read"}, "decision": "allow"})


def _unknown_decision(d: dict[str, Any]) -> None:
    d["rules"][0]["decision"] = "allow_everything"


def _default_allow(d: dict[str, Any]) -> None:
    d["default"] = "allow"


def _no_default(d: dict[str, Any]) -> None:
    del d["default"]


def _unknown_requirement(d: dict[str, Any]) -> None:
    d["rules"][2]["requires"] = ["vibes"]


def _unknown_role(d: dict[str, Any]) -> None:
    d["rules"][2]["roles"] = ["root"]


def _unknown_match_key(d: dict[str, Any]) -> None:
    d["rules"][0]["match"]["anything"] = True


def _allow_if_without_requires(d: dict[str, Any]) -> None:
    d["rules"][2]["requires"] = []


def _duplicate_rule(d: dict[str, Any]) -> None:
    d["rules"].append(copy.deepcopy(d["rules"][0]))


@pytest.mark.parametrize(
    "mutate",
    [
        _unknown_rule,
        _unknown_decision,
        _default_allow,
        _no_default,
        _unknown_requirement,
        _unknown_role,
        _unknown_match_key,
        _allow_if_without_requires,
        _duplicate_rule,
    ],
)
def test_a_matrix_breaking_a_rule_is_refused(mutate: Callable[[dict[str, Any]], None]) -> None:
    source = policy_source()
    parse_policy(dump(source), "matrix.yaml")  # la matrice de départ est valide
    mutate(source)
    with pytest.raises(CatalogError):
        parse_policy(dump(source), "matrix.yaml")


# --- yaml.safe_load uniquement ------------------------------------------------------------------


def test_the_yaml_reader_rejects_python_tags_that_an_unsafe_loader_would_build() -> None:
    # Un document par ailleurs valide : seul le tag fait la différence entre safe_load et load.
    with pytest.raises(CatalogError):
        parse_yaml_mapping(UNSAFE_YAML.encode(), "doc")
    assert parse_yaml_mapping(b"x: 1\n", "doc") == {"x": 1}


def test_python_object_tags_are_rejected_everywhere_a_yaml_is_read() -> None:
    skill = b"---\nname: x\nversion: 1\nstatus: draft\ndescription: d\ntools: []\n" + (
        b"y: !!python/object/apply:pathlib.Path ['/tmp/foreman-unsafe']\n---\n# Objectif\n"
    )
    for read in (
        lambda: parse_tool(UNSAFE_YAML.encode(), "tool"),
        lambda: parse_policy(UNSAFE_YAML.encode(), "matrix"),
        lambda: parse_referentiel(UNSAFE_YAML.encode(), "ref", "ref"),
        lambda: parse_skill(skill, "skill"),
    ):
        with pytest.raises(CatalogError):
            read()


# --- Skills : brouillon, hash, forme -----------------------------------------------------


def test_a_draft_skill_is_refused_outside_staging(workdir: tuple[Path, Path]) -> None:
    assert load(workdir, "staging").skills["go-backend-standard"].status == "draft"
    with pytest.raises(CatalogError):
        load(workdir, "production")


def test_a_published_skill_loads_in_production(workdir: tuple[Path, Path]) -> None:
    catalog, _ = workdir
    for path in (catalog / "skills").glob("*/SKILL.md"):
        path.write_text(
            path.read_text(encoding="utf-8").replace("status: draft", "status: published", 1),
            encoding="utf-8",
        )
    skills = load(workdir, "production").skills
    assert {s.status for s in skills.values()} == {"published"}


@pytest.mark.parametrize("name", sorted(S1_SKILLS))
def test_changing_one_byte_of_a_skill_changes_its_sha256(
    workdir: tuple[Path, Path], name: str
) -> None:
    catalog, _ = workdir
    path = catalog / "skills" / name / "SKILL.md"
    before = load(workdir).skills[name].sha256
    assert before == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert load(workdir).skills[name].sha256 == before  # stable tant que rien ne change
    path.write_bytes(path.read_bytes() + b" ")
    after = load(workdir).skills[name].sha256
    assert after != before
    assert after == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_skill_citing_an_unknown_tool_is_refused(workdir: tuple[Path, Path]) -> None:
    catalog, _ = workdir
    path = catalog / "skills" / "go-backend-standard" / "SKILL.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("tools: []", "tools: [server.exec_adhoc]"),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError):
        load(workdir)


def test_a_skill_whose_name_differs_from_its_folder_is_refused(
    workdir: tuple[Path, Path],
) -> None:
    catalog, _ = workdir
    (catalog / "skills" / "go-backend-standard").rename(catalog / "skills" / "other-name")
    with pytest.raises(CatalogError):
        load(workdir)


def _skill(
    front: str, body: str = "# Objectif\n# Instructions\n# Règles\n# Résultat attendu\n"
) -> bytes:
    return f"---\n{front}---\n{body}".encode()


GOOD_FRONT = "name: demo\nversion: 1\nstatus: draft\ndescription: d\ntools: []\n"


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(_skill(GOOD_FRONT.replace("version: 1", "version: '1'")), id="version-string"),
        pytest.param(_skill(GOOD_FRONT.replace("version: 1", "version: 1.5")), id="version-float"),
        pytest.param(_skill(GOOD_FRONT.replace("draft", "final")), id="unknown-status"),
        pytest.param(_skill(GOOD_FRONT + "owner: me\n"), id="unknown-front-matter-key"),
        pytest.param(_skill(GOOD_FRONT.replace("tools: []\n", "")), id="missing-tools"),
        pytest.param(_skill(GOOD_FRONT, "# Objectif\n"), id="missing-sections"),
        pytest.param(b"# Objectif\n", id="no-front-matter"),
        pytest.param(b"---\nname: demo\n# Objectif\n", id="unterminated-front-matter"),
    ],
)
def test_a_malformed_skill_is_refused(raw: bytes) -> None:
    parse_skill(_skill(GOOD_FRONT), "SKILL.md", expected_name="demo")  # la base est valide
    with pytest.raises(CatalogError):
        parse_skill(raw, "SKILL.md", expected_name="demo")


def test_an_oversized_catalog_file_is_refused_without_being_parsed(
    workdir: tuple[Path, Path],
) -> None:
    catalog, _ = workdir
    (catalog / "referentiels" / "environments.yaml").write_bytes(b"a: 1\n" + b"#" * 70_000)
    with pytest.raises(CatalogError):
        load(workdir)


def test_a_missing_matrix_stops_the_startup(workdir: tuple[Path, Path]) -> None:
    catalog, _ = workdir
    (catalog / "policy" / "matrix.yaml").unlink()
    with pytest.raises(CatalogError):
        load(workdir)


# --- Fermeture des schémas : un test par contournement -------------------------------------------

_CLOSED_OBJECT: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}


def _wrap(sub: object) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"a": sub},
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(_wrap(True), id="boolean-schema-property"),
        pytest.param(_wrap({}), id="empty-schema-no-type"),
        pytest.param(_wrap({"properties": {}}), id="properties-without-type"),
        pytest.param(
            _wrap({"enum": [{}], "properties": {"x": {"type": "string"}}}),
            id="properties-with-enum-and-no-type",
        ),
        pytest.param(_wrap({"type": "array"}), id="array-without-items"),
        pytest.param(_wrap({"type": "array", "items": True}), id="boolean-items"),
        pytest.param(
            _wrap(
                {
                    "type": "object",
                    "patternProperties": {"^x": {"type": "string"}},
                    "additionalProperties": False,
                }
            ),
            id="patternProperties",
        ),
        pytest.param(
            _wrap({"type": "object", "properties": {}, "unevaluatedProperties": False}),
            id="unevaluatedProperties-instead-of-closure",
        ),
        pytest.param(
            _wrap({"type": "object", "dependentSchemas": {"x": {}}, "additionalProperties": False}),
            id="dependentSchemas",
        ),
        pytest.param(
            _wrap({"type": "object", "properties": {}, "additionalProperties": {"type": "string"}}),
            id="additionalProperties-schema",
        ),
        pytest.param(
            _wrap({"type": ["object", "null"], "properties": {}}), id="type-list-with-object"
        ),
        pytest.param(_wrap({"anyOf": [{"type": "object", "properties": {}}]}), id="open-in-anyOf"),
        pytest.param(_wrap({"oneOf": [{"type": "object", "properties": {}}]}), id="open-in-oneOf"),
        pytest.param(_wrap({"allOf": [{"type": "object", "properties": {}}]}), id="open-in-allOf"),
        pytest.param(_wrap({"anyOf": [True]}), id="boolean-in-anyOf"),
        pytest.param(_wrap({"not": {"type": "string"}, "type": "string"}), id="not"),
        pytest.param(
            _wrap({"type": "string", "if": {"minLength": 1}, "then": {"maxLength": 3}}),
            id="if-then",
        ),
        pytest.param(
            _wrap(
                {"type": "array", "prefixItems": [{"type": "string"}], "items": {"type": "string"}}
            ),
            id="prefixItems",
        ),
        pytest.param(_wrap({"$ref": "#/$defs/x"}), id="ref"),
        pytest.param(
            {"type": "object", "properties": {}, "additionalProperties": False, "$defs": {"x": {}}},
            id="defs",
        ),
        pytest.param({"type": "string"}, id="root-not-an-object"),
        pytest.param({"properties": {}, "additionalProperties": False}, id="root-without-type"),
    ],
)
def test_every_schema_bypass_is_reported(schema: dict[str, Any]) -> None:
    assert schema_problems(_CLOSED_OBJECT) == []
    if schema.get("type") == "object":
        assert schema_problems(schema), "le contournement n'est pas signalé"
    source = copy.deepcopy(tool_source("server.healthcheck"))
    source["input"] = schema
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "server.healthcheck")


def test_closed_and_typed_nested_schemas_are_accepted() -> None:
    nested = _wrap(
        {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {"b": {"type": "string"}},
                    "additionalProperties": False,
                },
                {"type": "array", "items": {"type": "integer"}},
            ]
        }
    )
    assert schema_problems(nested) == []


# --- Outils : playbooks, registre, portée ----------------------------------------------------


def test_apply_playbook_resolves_reversibility_and_scope_per_playbook() -> None:
    tool = load_catalog(CATALOG_DIR, environment="staging").tools["server.apply_playbook"]
    boot = {"playbook": "bootstrap_project"}
    deploy = {"playbook": "deploy_compose"}
    # R6 ne s'applique qu'à reversible/compensable : ce sont ces valeurs que la gateway verra.
    assert tool.effective_reversibility(boot) == "compensable"
    assert tool.effective_reversibility(deploy) == "compensable"
    assert tool.effective_scope(boot).kind == "create"
    assert tool.effective_scope(boot).parent == "environment"
    assert (tool.effective_scope(deploy).kind, tool.effective_scope(deploy).target) == (
        "update",
        "project",
    )
    with pytest.raises(ValueError, match="playbook inconnu"):
        tool.effective_reversibility({"playbook": "rm_rf"})


def test_apply_playbook_is_staging_only_and_registers_the_project_slug() -> None:
    source = tool_source("server.apply_playbook")
    assert source["input"]["properties"]["environment"] == {"enum": ["staging"]}
    assert source["registry"]["external_id"] == "project"
    assert "run_id" in source["output"]


def _no_playbooks(d: dict[str, Any]) -> None:
    del d["playbooks"]


def _missing_playbook_entry(d: dict[str, Any]) -> None:
    del d["playbooks"]["deploy_compose"]


def _extra_playbook_entry(d: dict[str, Any]) -> None:
    d["playbooks"]["configure_caddy"] = d["playbooks"]["deploy_compose"]


def _top_level_scope_with_playbooks(d: dict[str, Any]) -> None:
    d["scope"] = {"kind": "update", "target": "project"}


def _playbook_scope_unknown_param(d: dict[str, Any]) -> None:
    d["playbooks"]["deploy_compose"]["scope"] = {"kind": "update", "target": "nope"}


def _playbook_irreversible_unknown_value(d: dict[str, Any]) -> None:
    d["playbooks"]["deploy_compose"]["reversibility"] = "per_playbook"


def _registry_id_unknown(d: dict[str, Any]) -> None:
    d["registry"]["external_id"] = "no_such_field"


def _write_without_registry(d: dict[str, Any]) -> None:
    del d["registry"]


def _root_not_object(d: dict[str, Any]) -> None:
    d["input"] = {"type": "string"}


@pytest.mark.parametrize(
    "mutate",
    [
        _no_playbooks,
        _missing_playbook_entry,
        _extra_playbook_entry,
        _top_level_scope_with_playbooks,
        _playbook_scope_unknown_param,
        _playbook_irreversible_unknown_value,
        _registry_id_unknown,
        _write_without_registry,
        _root_not_object,
    ],
)
def test_a_broken_apply_playbook_definition_is_refused(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    source = copy.deepcopy(tool_source("server.apply_playbook"))
    parse_tool(dump(source), "server.apply_playbook")
    mutate(source)
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "server.apply_playbook")


def test_playbooks_are_refused_on_a_tool_that_is_not_per_playbook() -> None:
    source = copy.deepcopy(tool_source("gitlab.create_group"))
    source["playbooks"] = {
        "x": {"reversibility": "compensable", "scope": {"kind": "update", "target": "path"}}
    }
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "gitlab.create_group")


def test_a_tool_without_any_scope_is_refused() -> None:
    source = copy.deepcopy(tool_source("gitlab.create_group"))
    del source["scope"]
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "gitlab.create_group")


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param({"kind": "update", "parent": "parent_group_id"}, id="update-with-parent"),
        pytest.param({"kind": "update"}, id="update-without-target"),
        pytest.param(
            {"kind": "create", "parent": "parent_group_id", "target": "path"},
            id="create-with-target",
        ),
        pytest.param({"kind": "create"}, id="create-without-parent"),
        pytest.param({"kind": "read"}, id="read-scope-on-a-write-tool"),
    ],
)
def test_a_malformed_scope_is_refused(scope: dict[str, Any]) -> None:
    source = copy.deepcopy(tool_source("gitlab.create_group"))
    source["scope"] = scope
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "gitlab.create_group")


def test_a_read_tool_with_a_write_scope_is_refused() -> None:
    source = copy.deepcopy(tool_source("server.healthcheck"))
    source["scope"] = {"kind": "update", "target": "project"}
    with pytest.raises(CatalogError):
        parse_tool(dump(source), "server.healthcheck")


# --- Matrice : classe obligatoire, écritures, environnements, liaison des règles -------------


def _rule(d: dict[str, Any], rule_id: str) -> dict[str, Any]:
    return next(r for r in d["rules"] if r["id"] == rule_id)


def _no_class(d: dict[str, Any]) -> None:
    del _rule(d, "R1-lecture")["match"]["class"]


def _write_rule_is_allow(d: dict[str, Any]) -> None:
    rule = _rule(d, "R6-ecriture-staging")
    rule["decision"] = "allow"
    rule["requires"] = []


def _foreign_write_rule_is_allow(d: dict[str, Any]) -> None:
    d["rules"].append(
        {"id": "R9-hors-registre", "match": {"class": "write_foreign"}, "decision": "allow"}
    )


def _destructive_rule_is_allow(d: dict[str, Any]) -> None:
    d["rules"].append(
        {"id": "R10-destructif", "match": {"class": "destructive"}, "decision": "allow"}
    )


def _write_rule_without_plan_approval(d: dict[str, Any]) -> None:
    _rule(d, "R6-ecriture-staging")["requires"] = ["admin_approved"]


def _rule_on_unknown_environment(d: dict[str, Any]) -> None:
    _rule(d, "R1-lecture")["match"]["env"] = "qa"


def _read_rule_bent_to_write(d: dict[str, Any]) -> None:
    _rule(d, "R1-lecture")["match"]["class"] = "write_registry"


def _write_rule_bent_to_read(d: dict[str, Any]) -> None:
    rule = _rule(d, "R6-ecriture-staging")
    rule["match"]["class"] = "read"
    rule["decision"] = "allow"
    rule["requires"] = []


def _staging_rule_moved_to_production(d: dict[str, Any]) -> None:
    d["autonomy"]["environments"]["production"] = {"max_level": 3, "admin_approval_required": True}
    _rule(d, "R6-ecriture-staging")["match"]["env"] = "production"


@pytest.mark.parametrize(
    "mutate",
    [
        _no_class,
        _write_rule_is_allow,
        _foreign_write_rule_is_allow,
        _destructive_rule_is_allow,
        _write_rule_without_plan_approval,
        _rule_on_unknown_environment,
        _read_rule_bent_to_write,
        _write_rule_bent_to_read,
        _staging_rule_moved_to_production,
    ],
)
def test_a_matrix_weakening_a_rule_is_refused(mutate: Callable[[dict[str, Any]], None]) -> None:
    source = policy_source()
    mutate(source)
    with pytest.raises(CatalogError):
        parse_policy(dump(source), "matrix.yaml")


# --- Traçabilité : empreintes au format du contrat -------------------------------------------


def test_hashes_use_the_contract_format_and_fit_a_skill_ref() -> None:
    catalog = load_catalog(CATALOG_DIR, environment="staging")
    for skill in catalog.skills.values():
        ref = SkillRef(name=skill.name, version=skill.version, sha256=skill.sha256)
        assert ref.sha256.startswith("sha256:")
    assert catalog.policy_sha256.startswith("sha256:") and len(catalog.policy_sha256) == 71
    assert all(r.sha256.startswith("sha256:") for r in catalog.referentiels.values())


# --- Aucune fuite de contenu, même dans la chaîne d'exceptions -------------------------------

SECRET = "jeton-glpat-ne-doit-pas-sortir"  # noqa: S105


def _full_trace(exc: BaseException) -> str:
    return "".join(traceback.format_exception(exc))


def test_catalog_errors_never_leak_file_contents_even_through_the_cause_chain() -> None:
    tool = copy.deepcopy(tool_source("server.healthcheck"))
    tool["timeout_s"] = SECRET
    policy = policy_source()
    policy["default"] = SECRET
    skill_front = f"name: demo\nversion: {SECRET}\nstatus: draft\ndescription: d\ntools: []\n"
    attempts: list[Callable[[], object]] = [
        lambda: parse_yaml_mapping(f"token: {SECRET}\n  bad: [".encode(), "doc"),
        lambda: parse_tool(dump(tool), "tool"),
        lambda: parse_policy(dump(policy), "matrix"),
        lambda: parse_skill(_skill(skill_front), "SKILL.md"),
        lambda: parse_referentiel(f"{SECRET}: [".encode(), "ref", "ref"),
    ]
    for attempt in attempts:
        with pytest.raises(CatalogError) as excinfo:
            attempt()
        assert SECRET not in str(excinfo.value)
        assert SECRET not in _full_trace(excinfo.value)


# --- Texte : LF, UTF-8, sans BOM -------------------------------------------------------------


def test_crlf_and_bom_are_refused_with_a_clear_message() -> None:
    with pytest.raises(CatalogError, match="CRLF"):
        parse_yaml_mapping(b"a: 1\r\nb: 2\r\n", "doc")
    with pytest.raises(CatalogError, match="BOM"):
        parse_yaml_mapping(b"\xef\xbb\xbfa: 1\n", "doc")
    with pytest.raises(CatalogError, match="CRLF"):
        parse_skill(_skill(GOOD_FRONT).replace(b"\n", b"\r\n"), "SKILL.md")


# --- Lecture des fichiers : fichiers réguliers sous la racine --------------------------------


def test_a_symlink_is_refused_even_inside_the_catalog(tmp_path: Path) -> None:
    (tmp_path / "real.yaml").write_text("a: 1\n")
    (tmp_path / "link.yaml").symlink_to(tmp_path / "real.yaml")
    assert read_catalog_file(tmp_path / "real.yaml", tmp_path) == b"a: 1\n"
    with pytest.raises(CatalogError):
        read_catalog_file(tmp_path / "link.yaml", tmp_path)


def test_a_path_resolving_outside_the_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.yaml").write_text("a: 1\n")
    (root / "dir_link").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(CatalogError):
        read_catalog_file(root / "dir_link" / "outside.yaml", root)


def test_a_fifo_or_a_directory_is_refused_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe.yaml")
    (tmp_path / "dir.yaml").mkdir()
    with pytest.raises(CatalogError):
        read_catalog_file(tmp_path / "pipe.yaml", tmp_path)
    with pytest.raises(CatalogError):
        read_catalog_file(tmp_path / "dir.yaml", tmp_path)


def test_the_size_limit_is_exact(tmp_path: Path) -> None:
    from foreman.core.catalog import MAX_CATALOG_FILE_BYTES

    (tmp_path / "ok.yaml").write_bytes(b"#" * MAX_CATALOG_FILE_BYTES)
    (tmp_path / "big.yaml").write_bytes(b"#" * (MAX_CATALOG_FILE_BYTES + 1))
    assert len(read_catalog_file(tmp_path / "ok.yaml", tmp_path)) == MAX_CATALOG_FILE_BYTES
    with pytest.raises(CatalogError):
        read_catalog_file(tmp_path / "big.yaml", tmp_path)


# --- Démarrage -------------------------------------------------------------------------------


def test_a_missing_catalog_directory_fails_with_a_clear_message(tmp_path: Path) -> None:
    with pytest.raises(CatalogError, match="FOREMAN_CATALOG_DIR"):
        load_catalog(tmp_path / "absent", environment="staging")


@pytest.mark.parametrize("folder", ["skills", "referentiels"])
def test_an_empty_skills_or_referentiels_folder_is_refused(
    workdir: tuple[Path, Path], folder: str
) -> None:
    catalog, _ = workdir
    shutil.rmtree(catalog / folder)
    (catalog / folder).mkdir()
    with pytest.raises(CatalogError, match="incomplet"):
        load(workdir)


def test_configure_loads_the_catalog_at_startup() -> None:
    app = configure(Profile.CLI)
    assert app.catalog is not None
    assert set(app.catalog.tools) == set(S1_TOOLS)


def test_startup_fails_clearly_on_a_missing_catalog_or_a_draft_skill_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FOREMAN_CATALOG_DIR", str(tmp_path / "absent"))
    with pytest.raises(CatalogError, match="FOREMAN_CATALOG_DIR"):
        configure(Profile.CLI)
    monkeypatch.setenv("FOREMAN_CATALOG_DIR", str(CATALOG_DIR))
    monkeypatch.setenv("FOREMAN_ENVIRONMENT", "production")
    with pytest.raises(CatalogError, match="brouillon"):
        configure(Profile.CLI)
