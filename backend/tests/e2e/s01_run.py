"""Le scénario S1 de bout en bout, en processus et en mémoire (aucun réseau, aucun vrai modèle).

Partagé par le test nominal et par l'export du fixture du front (`make s01-fixture`) : les deux
rejouent EXACTEMENT la même chose, par l'API HTTP, avec le modèle rejoué et les faux adaptateurs.
"""

import asyncio
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx

from foreman.bootstrap.configure import App, Profile, configure
from foreman.core.events import AnyEvent
from foreman.core.ports import EventLog
from foreman.surfaces.web.app import create_app

USER_MESSAGE = "Crée le projet Safe Eat : GitLab, puis déploiement en staging."
BASE_TIME = datetime(2026, 10, 20, 9, 0, 0, tzinfo=UTC)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HEX32 = re.compile(r"^(approval-)?[0-9a-f]{32}$")  # `card_id` : brut ou préfixé


DEV_HEADERS, ADMIN_HEADERS = {"X-Forwarded-User": "dev"}, {"X-Forwarded-User": "admin"}


def configure_web() -> App:
    """Web avec `dev` (développeur) et `admin` (team_admin) : seul l'admin valide (#248)."""
    os.environ["FOREMAN_AUTH_MODE"] = "proxy_header"
    os.environ["FOREMAN_DEV_MEMBERS"] = "dev:developer,admin:team_admin"
    try:
        return configure(Profile.WEB)
    finally:
        del os.environ["FOREMAN_AUTH_MODE"], os.environ["FOREMAN_DEV_MEMBERS"]


async def _wait_for(events: EventLog, project_id: UUID, kind: str, field: str, value: str) -> None:
    subscription = events.subscribe(project_id)
    try:
        async with asyncio.timeout(10):
            while (event := await subscription.next()) is not None:
                data = event.data.model_dump(mode="json")
                if event.type == kind and data.get(field) == value:
                    return
    finally:
        subscription.close()
    raise AssertionError("flux fermé avant l'événement attendu")


async def run_s01() -> tuple[App, UUID, list[AnyEvent]]:
    """Joue S1 : message, plan, approbation, exécution. Rend l'application, le projet, le flux."""
    state = configure_web()
    transport = httpx.ASGITransport(app=create_app(state))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=DEV_HEADERS
    ) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        planned = asyncio.create_task(
            _wait_for(state.events, project_id, "turn_status", "status", "completed")
        )
        await asyncio.sleep(0)  # l'abonnement précède le message
        await client.post(f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE})
        await planned
        card = next(
            e.data for e in await state.events.read_after(project_id, 0) if e.type == "card"
        )
        done = asyncio.create_task(
            _wait_for(state.events, project_id, "card", "state", "succeeded")
        )
        await asyncio.sleep(0)
        approval = await client.post(
            f"/api/projects/{project_id}/plans/{card.plan_id}/approvals",  # type: ignore[union-attr]
            json={"plan_hash": card.plan_hash, "decision": "approved"},  # type: ignore[union-attr]
            headers=ADMIN_HEADERS,
        )
        assert approval.status_code == 201
        await done
    return state, project_id, await state.events.read_after(project_id, 0)


def normalize(events: list[AnyEvent]) -> list[dict[str, Any]]:
    """Événements sérialisés, identifiants et dates remplacés par des valeurs stables.

    Les UUID (et les `card_id` qui en dérivent) sont numérotés dans l'ordre d'apparition ; le hash
    du plan dépend du projet, donc il est numéroté aussi ; `at` devient `BASE_TIME + seq` secondes ;
    `elapsed_s` (durée réelle) vaut 0. Le reste (empreintes de Skills, ressources) est déterministe.
    """
    uuids: dict[str, str] = {}
    hashes: dict[str, str] = {}

    def stable_uuid(raw: str) -> str:
        return uuids.setdefault(raw, f"00000000-0000-4000-8000-{len(uuids) + 1:012d}")

    def walk(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            # `author` : id du compte de dev, déjà constant ; ne décale pas la numérotation.
            return {k: v if k == "author" else walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if isinstance(value, str):
            if _UUID.match(value):
                return stable_uuid(value)
            if hexed := _HEX32.match(value):
                prefix = hexed.group(1) or ""
                return prefix + stable_uuid(str(uuid.UUID(value[len(prefix) :]))).replace("-", "")
            if key == "plan_hash":
                return hashes.setdefault(value, f"sha256:{len(hashes) + 1:064x}")
        if key == "elapsed_s":
            return 0
        return value

    out: list[dict[str, Any]] = []
    for event in events:
        raw = event.model_dump(mode="json")
        raw["at"] = (BASE_TIME + timedelta(seconds=event.seq)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out.append(walk(raw))
    return out
