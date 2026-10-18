import os
from pathlib import Path

import pytest

from foreman.config.env import ENV_CATALOG_DIR

CATALOG_DIR = Path(__file__).resolve().parents[2] / "catalog"


@pytest.fixture(autouse=True)
def catalog_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les tests tournent depuis `backend/` : on pointe vers le catalogue du dépôt."""
    monkeypatch.setenv(ENV_CATALOG_DIR, os.fspath(CATALOG_DIR))
