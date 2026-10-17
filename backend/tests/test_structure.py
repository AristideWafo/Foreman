"""Garde-fous de structure : ce que import-linter ne couvre pas."""

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
