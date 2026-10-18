"""Catalogue : chargement, refus (un test par règle) et traçabilité des Skills par hash."""

import copy
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from foreman.core.catalog import (
    REGISTRY_MARKING,
    Catalog,
    CatalogError,
    parse_policy,
    parse_referentiel,
    parse_skill,
    parse_tool,
    parse_yaml_mapping,
)
from foreman.infra.file_catalog import DEFAULT_TOOLS_ROOT, load_catalog

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
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    assert load(workdir).skills[name].sha256 == before  # stable tant que rien ne change
    path.write_bytes(path.read_bytes() + b" ")
    after = load(workdir).skills[name].sha256
    assert after != before
    assert after == hashlib.sha256(path.read_bytes()).hexdigest()


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


def test_catalog_errors_never_echo_file_contents(workdir: tuple[Path, Path]) -> None:
    catalog, _ = workdir
    secret = "jeton-glpat-ne-doit-pas-sortir"  # noqa: S105
    (catalog / "referentiels" / "environments.yaml").write_text(
        f"token: {secret}\n  bad: [", encoding="utf-8"
    )
    with pytest.raises(CatalogError) as excinfo:
        load(workdir)
    assert secret not in str(excinfo.value)
