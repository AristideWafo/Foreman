"""Le scénario S2 (environnement non précisé) de bout en bout, en processus et en mémoire.

Partagé par le test e2e et par l'export du fixture du front (`make s02-fixture`). Le modèle est
rejoué (`catalog/recordings/s02.yaml`) : aucun réseau, aucun vrai modèle.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import httpx
from s01_run import _wait_for

from foreman.bootstrap.configure import App, Profile, configure
from foreman.core.events import AnyEvent
from foreman.surfaces.web.app import create_app

USER_MESSAGE = "Prépare le projet Safe Eat : GitLab puis déploiement."


@dataclass(frozen=True)
class S2Run:
    state: App
    project_id: UUID
    after_ask: list[AnyEvent]  # flux observé après le seul tour 1
    answer_status: int  # code HTTP de la route de réponse
    events: list[AnyEvent]  # flux final


async def run_s02() -> S2Run:
    """Joue S2 : message sans environnement, clarification, réponse `staging`, plan."""
    state = configure(Profile.WEB)
    transport = httpx.ASGITransport(app=create_app(state))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        asked = asyncio.create_task(
            _wait_for(state.events, project_id, "turn_status", "status", "completed")
        )
        await asyncio.sleep(0)  # l'abonnement précède le message
        await client.post(f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE})
        await asked
        after_ask = await state.events.read_after(project_id, 0)

        planned = asyncio.create_task(
            _wait_for(state.events, project_id, "turn_status", "status", "completed")
        )
        await asyncio.sleep(0)
        answer = await client.post(
            f"/api/projects/{project_id}/questions/q1-1",
            json={"decision": "answer", "value": "staging"},
        )
        await planned
    events = await state.events.read_after(project_id, 0)
    return S2Run(state, project_id, after_ask, answer.status_code, events)
