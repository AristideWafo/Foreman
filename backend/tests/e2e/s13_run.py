"""Le scénario S13 (lecture GitLab dans le chat), en processus et en mémoire.

Le modèle rejoue `catalog/recordings/s13.yaml` : la question donne un appel `gitlab.list_groups`,
le résultat d'outil (hash du texte canonique) donne la réponse finale. Aucune carte, aucun plan.
"""

import asyncio
from dataclasses import dataclass
from uuid import UUID

import httpx
from s01_run import DEV_HEADERS, _wait_for, configure_web

from foreman.bootstrap.configure import App
from foreman.core.events import AnyEvent
from foreman.surfaces.web.app import create_app

USER_MESSAGE = "Quels sont les groupes GitLab de la plateforme ?"


@dataclass(frozen=True)
class S13Run:
    state: App
    project_id: UUID
    events: list[AnyEvent]


async def run_s13() -> S13Run:
    state = configure_web()
    transport = httpx.ASGITransport(app=create_app(state))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=DEV_HEADERS
    ) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        done = asyncio.create_task(
            _wait_for(state.events, project_id, "turn_status", "status", "completed")
        )
        await asyncio.sleep(0)  # l'abonnement précède le message
        await client.post(f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE})
        await done
    return S13Run(state, project_id, await state.events.read_after(project_id, 0))
