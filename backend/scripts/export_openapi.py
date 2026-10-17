"""Écrit le schéma OpenAPI sur stdout (source des types TypeScript générés)."""

import json
import sys

from foreman.surfaces.web.app import create_app

sys.stdout.write(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
