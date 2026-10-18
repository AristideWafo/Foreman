"""Lecteur du catalogue sur disque. Synchrone : appelé au démarrage, jamais dans la boucle async.

Les définitions d'outils vivent à côté de leur connecteur (`integrations/<c>/tools/*.yaml`) ;
elles sont lues par chemin, sans importer `integrations` (la couche `infra` ne dépend pas d'elle).
"""

import os
from pathlib import Path

from foreman.config.env import DEFAULT_CATALOG_DIR, ENV_CATALOG_DIR
from foreman.core.catalog import (
    MAX_CATALOG_FILE_BYTES,
    Catalog,
    CatalogError,
    ToolDefinition,
    build_catalog,
    parse_policy,
    parse_referentiel,
    parse_skill,
    parse_tool,
    sha256_hex,
)

DEFAULT_TOOLS_ROOT = Path(__file__).resolve().parents[1] / "integrations"
SKILL_FILE = "SKILL.md"
POLICY_FILE = Path("policy") / "matrix.yaml"


def catalog_dir_from_env() -> Path:
    return Path(os.environ.get(ENV_CATALOG_DIR, DEFAULT_CATALOG_DIR))


def _read(path: Path) -> bytes:
    """Lit un fichier du catalogue en bornant sa taille (un fichier géant échoue avant lecture)."""
    try:
        if path.stat().st_size > MAX_CATALOG_FILE_BYTES:
            raise CatalogError(f"{path.name}: fichier trop volumineux")
        return path.read_bytes()
    except OSError as exc:
        raise CatalogError(f"{path.name}: lecture impossible") from exc


def load_catalog(
    root: Path | None = None, *, environment: str, tools_root: Path | None = None
) -> Catalog:
    """Charge et valide tout le catalogue. Lève `CatalogError` au premier défaut."""
    base = root if root is not None else catalog_dir_from_env()
    connectors_dir = tools_root if tools_root is not None else DEFAULT_TOOLS_ROOT

    tools: list[ToolDefinition] = []
    for path in sorted(connectors_dir.glob("*/tools/*.yaml")):
        connector = path.parent.parent.name
        source = f"{connector}/tools/{path.name}"
        tool = parse_tool(_read(path), source)
        if tool.connector != connector or tool.tool != f"{connector}.{path.stem}":
            raise CatalogError(f"{source}: le nom de l'outil ne suit pas son emplacement")
        tools.append(tool)

    skills = [
        parse_skill(
            _read(path), f"skills/{path.parent.name}/{SKILL_FILE}", expected_name=path.parent.name
        )
        for path in sorted((base / "skills").glob(f"*/{SKILL_FILE}"))
    ]
    referentiels = [
        parse_referentiel(_read(path), path.stem, f"referentiels/{path.name}")
        for path in sorted((base / "referentiels").glob("*.yaml"))
    ]
    policy_raw = _read(base / POLICY_FILE)
    return build_catalog(
        tools=tools,
        skills=skills,
        referentiels=referentiels,
        policy=parse_policy(policy_raw, POLICY_FILE.as_posix()),
        policy_sha256=sha256_hex(policy_raw),
        environment=environment,
    )
