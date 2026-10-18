"""Écrit le schéma OpenAPI sur stdout (source des types TypeScript générés)."""

import json
import os
import sys
from pathlib import Path

from foreman.config.env import ENV_CATALOG_DIR
from foreman.surfaces.web.app import create_app

# Lancé depuis `backend/` : le catalogue du dépôt est à la racine.
os.environ.setdefault(ENV_CATALOG_DIR, str(Path(__file__).resolve().parents[2] / "catalog"))

sys.stdout.write(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
