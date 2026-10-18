"""Lecteur du catalogue sur disque. Synchrone : appelé au démarrage, jamais dans la boucle async.

Les définitions d'outils vivent à côté de leur connecteur (`integrations/<c>/tools/*.yaml`) ;
elles sont lues par chemin, sans importer `integrations` (la couche `infra` ne dépend pas d'elle).
Un Skill `draft` fait échouer le démarrage hors staging (voulu).
"""

import os
import stat
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
    sha256_ref,
)

DEFAULT_TOOLS_ROOT = Path(__file__).resolve().parents[1] / "integrations"
SKILL_FILE = "SKILL.md"
POLICY_FILE = Path("policy") / "matrix.yaml"


def catalog_dir_from_env() -> Path:
    return Path(os.environ.get(ENV_CATALOG_DIR, DEFAULT_CATALOG_DIR))


def read_catalog_file(path: Path, base: Path) -> bytes:
    """Lit un fichier régulier situé sous `base`, borné en taille.

    Refuse un lien symbolique final (`O_NOFOLLOW`), tout ce qui n'est pas un fichier régulier
    (FIFO, périphérique, dossier) et tout chemin qui sort de `base` une fois résolu. La lecture
    bornée (`MAX + 1`) évite de charger un fichier géant.
    """
    name = path.name
    try:
        if not path.resolve().is_relative_to(base.resolve()):
            raise CatalogError(f"{name}: hors du catalogue")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        raise CatalogError(f"{name}: lecture impossible") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CatalogError(f"{name}: un fichier régulier est attendu")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            data = handle.read(MAX_CATALOG_FILE_BYTES + 1)
    except OSError:
        raise CatalogError(f"{name}: lecture impossible") from None
    finally:
        os.close(fd)
    if len(data) > MAX_CATALOG_FILE_BYTES:
        raise CatalogError(f"{name}: fichier trop volumineux")
    return data


def _nonempty(paths: list[Path], what: str) -> list[Path]:
    if not paths:
        raise CatalogError(f"catalogue incomplet : aucun fichier dans {what}")
    return paths


def load_catalog(
    root: Path | None = None, *, environment: str, tools_root: Path | None = None
) -> Catalog:
    """Charge et valide tout le catalogue. Lève `CatalogError` au premier défaut."""
    base = root if root is not None else catalog_dir_from_env()
    connectors_dir = tools_root if tools_root is not None else DEFAULT_TOOLS_ROOT
    if not base.is_dir():
        raise CatalogError(
            f"répertoire du catalogue introuvable ({ENV_CATALOG_DIR}, "
            f"défaut « {DEFAULT_CATALOG_DIR} » relatif au répertoire courant)"
        )

    tools: list[ToolDefinition] = []
    for path in _nonempty(sorted(connectors_dir.glob("*/tools/*.yaml")), "integrations/*/tools"):
        connector = path.parent.parent.name
        source = f"{connector}/tools/{path.name}"
        tool = parse_tool(read_catalog_file(path, connectors_dir), source)
        if tool.connector != connector or tool.tool != f"{connector}.{path.stem}":
            raise CatalogError(f"{source}: le nom de l'outil ne suit pas son emplacement")
        tools.append(tool)

    skill_files = _nonempty(sorted((base / "skills").glob(f"*/{SKILL_FILE}")), "skills/")
    skills = [
        parse_skill(
            read_catalog_file(path, base),
            f"skills/{path.parent.name}/{SKILL_FILE}",
            expected_name=path.parent.name,
        )
        for path in skill_files
    ]
    ref_files = _nonempty(sorted((base / "referentiels").glob("*.yaml")), "referentiels/")
    referentiels = [
        parse_referentiel(read_catalog_file(path, base), path.stem, f"referentiels/{path.name}")
        for path in ref_files
    ]
    policy_raw = read_catalog_file(base / POLICY_FILE, base)
    return build_catalog(
        tools=tools,
        skills=skills,
        referentiels=referentiels,
        policy=parse_policy(policy_raw, POLICY_FILE.as_posix()),
        policy_sha256=sha256_ref(policy_raw),
        environment=environment,
    )
