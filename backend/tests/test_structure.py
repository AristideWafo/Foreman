"""Garde-fous de structure : ce que import-linter ne couvre pas."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "foreman"
FORBIDDEN_DIRS = {"utils", "common", "helpers", "services", "vendors", "misc"}
MAX_IMPORT_EXCEPTIONS = 0  # voir docs/DEBT.md


def test_no_catch_all_packages() -> None:
    found = {p.name for p in SRC.rglob("*") if p.is_dir() and p.name in FORBIDDEN_DIRS}
    assert not found, f"dossiers fourre-tout interdits : {sorted(found)}"


def test_import_exceptions_are_frozen() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    contracts = config["tool"]["importlinter"]["contracts"]
    ignored = sum(len(c.get("ignore_imports", [])) for c in contracts)
    assert ignored <= MAX_IMPORT_EXCEPTIONS, "nouvelle exception de couche : voir docs/DEBT.md"


def test_the_container_bounds_graceful_shutdown() -> None:
    """Sans borne, un flux SSE ouvert retarde l'arrêt jusqu'au SIGKILL à chaque déploiement."""
    dockerfile = (ROOT.parent / "deploy" / "Dockerfile").read_text()
    cmd = next(line for line in dockerfile.splitlines() if line.startswith("CMD "))
    assert "--timeout-graceful-shutdown" in cmd


def test_no_mcp_outside_the_gateway() -> None:
    """ADR 0003 : aucun serveur MCP ni `mcp_servers` ; la gateway reste le seul chemin."""
    pattern = re.compile(r"mcp_servers|^\s*(import|from)\s+mcp\b", re.M)
    found = [p.name for p in SRC.rglob("*.py") if pattern.search(p.read_text())]
    assert not found, f"MCP interdit (ADR 0003) : {found}"
