"""Écrit sur stdout les événements normalisés du scénario S1 (fixture des cartes du front).

Lancé par `make s01-fixture` depuis `backend/`. Rejoue S1 comme le test nominal : même code.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from foreman.config.env import ENV_CATALOG_DIR

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault(ENV_CATALOG_DIR, str(ROOT / "catalog"))
os.environ.pop("FOREMAN_DATABASE_URL", None)  # S1 tourne toujours en mémoire
sys.path.insert(0, str(ROOT / "backend" / "tests" / "e2e"))

from s01_run import normalize, run_s01  # noqa: E402


async def main() -> None:
    _, _, events = await run_s01()
    sys.stdout.write(json.dumps(normalize(events), indent=2, ensure_ascii=False) + "\n")


asyncio.run(main())
