"""Le scénario S11 (même demande rejouée, aucune ressource en double), en processus et en mémoire.

Partagé par le test e2e, le test PostgreSQL de redémarrage et l'export du fixture du front
(`make s11-fixture`). Le modèle rejoue `catalog/recordings/s01.yaml` : le MÊME message donne la
même réponse, donc le même `plan_hash` (aucun nouvel enregistrement).
"""

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from s01_run import ADMIN_HEADERS, DEV_HEADERS, USER_MESSAGE, _wait_for, configure_web

from foreman.bootstrap.configure import App
from foreman.core.events import AnyEvent
from foreman.core.store import ResourceRecord
from foreman.surfaces.web.app import create_app


@dataclass(frozen=True)
class Round:
    """Un tour complet : message, plan, validation, exécution réussie."""

    plan: Any  # carte plan proposée (PlanCardData)
    events: list[AnyEvent]  # flux complet du projet à la fin du tour


async def play_round(client: httpx.AsyncClient, state: App, project_id: UUID) -> Round:
    """Joue S1 une fois dans un projet existant : le flux n'est lu qu'à partir du tour courant."""
    before = len(await state.events.read_after(project_id, 0))
    planned = asyncio.create_task(
        _wait_for(state.events, project_id, "turn_status", "status", "completed")
    )
    await asyncio.sleep(0)  # l'abonnement précède le message
    await client.post(f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE})
    await planned
    new = (await state.events.read_after(project_id, 0))[before:]
    card = next(e.data for e in new if e.type == "card" and e.data.kind == "plan")
    done = asyncio.create_task(_wait_for(state.events, project_id, "card", "state", "succeeded"))
    await asyncio.sleep(0)
    approval = await client.post(
        f"/api/projects/{project_id}/plans/{card.plan_id}/approvals",  # type: ignore[union-attr]
        json={"plan_hash": card.plan_hash, "decision": "approved"},  # type: ignore[union-attr]
        headers=ADMIN_HEADERS,
    )
    assert approval.status_code == 201
    await done
    return Round(card, await state.events.read_after(project_id, 0))


@dataclass(frozen=True)
class S11Run:
    state: App
    project_id: UUID
    first: Round
    second: Round
    registry_after_first: list[ResourceRecord]
    registry_after_second: list[ResourceRecord]
    fakes_after_first: dict[str, Any]
    fakes_after_second: dict[str, Any]


def snapshot_fakes(state: App) -> dict[str, Any]:
    """Contenu des faux (groupes, dépôts, projets serveur) : de quoi prouver « rien de plus »."""
    adapters = state.gateway._adapters  # type: ignore[union-attr]
    gitlab = getattr(adapters["gitlab"], "_fake", adapters["gitlab"])  # ConfiguredGitLab hors CI
    return {
        "groups": sorted(gitlab.groups),
        "projects": sorted(gitlab.projects),
        "server_projects": sorted(adapters["server"].projects),
        "runs": list(adapters["server"].runs),
    }


async def run_s11() -> S11Run:
    """Joue S11 : S1 deux fois, avec le même message, sur le même projet."""
    state = configure_web()
    transport = httpx.ASGITransport(app=create_app(state))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=DEV_HEADERS
    ) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        first = await play_round(client, state, project_id)
        registry_1 = await state.stores.registry.list_for_project(project_id)
        fakes_1 = snapshot_fakes(state)
        second = await play_round(client, state, project_id)
        registry_2 = await state.stores.registry.list_for_project(project_id)
        fakes_2 = snapshot_fakes(state)
    return S11Run(state, project_id, first, second, registry_1, registry_2, fakes_1, fakes_2)
