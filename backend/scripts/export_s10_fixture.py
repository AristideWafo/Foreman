"""Écrit sur stdout les événements normalisés du scénario S10 (fixture des cartes du front).

Lancé par `make s10-fixture` depuis `backend/`. Rejoue S10 comme le test e2e : même code.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from foreman.config.env import ENV_CATALOG_DIR

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault(ENV_CATALOG_DIR, str(ROOT / "catalog"))
os.environ.pop("FOREMAN_DATABASE_URL", None)  # S10 tourne toujours en mémoire
sys.path.insert(0, str(ROOT / "backend" / "tests" / "e2e"))

from s01_run import normalize  # noqa: E402
from s10_run import run_s10  # noqa: E402


async def main() -> None:
    run = await run_s10()
    sys.stdout.write(json.dumps(normalize(run.events), indent=2, ensure_ascii=False) + "\n")


asyncio.run(main())
