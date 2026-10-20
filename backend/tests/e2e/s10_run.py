"""Le scénario S10 (production sans droit) de bout en bout, en processus et en mémoire.

Partagé par le test e2e et par l'export du fixture du front (`make s10-fixture`). Le modèle est
rejoué (`catalog/recordings/s10.yaml`) ; l'identité passe par l'en-tête `X-Forwarded-User` comme
derrière Traefik, avec les membres fictifs `dev:developer` et `admin:team_admin`.
"""

import asyncio
import os
from dataclasses import dataclass
from uuid import UUID

import httpx
from s01_run import _wait_for

from foreman.bootstrap.configure import App, Profile, configure
from foreman.core.events import AnyEvent
from foreman.surfaces.web.app import create_app

USER_MESSAGE = "Déploie Safe Eat en production"


@dataclass(frozen=True)
class S10Run:
    state: App
    project_id: UUID
    plan_id: UUID
    after_plan: list[AnyEvent]  # flux après le tour de l'agent
    dev_validation_attempt: httpx.Response  # le développeur tente de valider : 403
    after_dev_validation_attempt: list[AnyEvent]
    dev_approval: httpx.Response  # l'administrateur donne la validation « développeur » : 202
    after_dev_approval: list[AnyEvent]
    executions_after_dev_approval: list[UUID]  # exécutions en base à ce moment
    dev_admin_attempt: httpx.Response  # le développeur appelle admin-approvals : 403
    after_dev_attempt: list[AnyEvent]
    admin_approval: httpx.Response  # l'administrateur approuve : 201
    events: list[AnyEvent]  # flux final


async def run_s10() -> S10Run:
    """Joue S10 : message, validation admin (202), essais interdits du dev, approbation admin."""
    os.environ["FOREMAN_AUTH_MODE"] = "proxy_header"
    os.environ["FOREMAN_DEV_MEMBERS"] = "dev:developer,admin:team_admin"
    try:
        state = configure(Profile.WEB)
    finally:
        del os.environ["FOREMAN_AUTH_MODE"], os.environ["FOREMAN_DEV_MEMBERS"]
    transport = httpx.ASGITransport(app=create_app(state))
    dev, admin = {"X-Forwarded-User": "dev"}, {"X-Forwarded-User": "admin"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"}, headers=dev)).json()[
                "id"
            ]
        )
        planned = asyncio.create_task(
            _wait_for(state.events, project_id, "turn_status", "status", "completed")
        )
        await asyncio.sleep(0)  # l'abonnement précède le message
        await client.post(
            f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE}, headers=dev
        )
        await planned
        after_plan = await state.events.read_after(project_id, 0)
        card = next(e.data for e in after_plan if e.type == "card")
        body = {"plan_hash": card.plan_hash, "decision": "approved"}  # type: ignore[union-attr]
        plan_url = f"/api/projects/{project_id}/plans/{card.plan_id}"  # type: ignore[union-attr]

        dev_validation_attempt = await client.post(f"{plan_url}/approvals", json=body, headers=dev)
        after_dev_validation_attempt = await state.events.read_after(project_id, 0)
        dev_approval = await client.post(f"{plan_url}/approvals", json=body, headers=admin)
        after_dev_approval = await state.events.read_after(project_id, 0)
        executions = [r.execution_id for r in await state.stores.executions.list_resumable()]
        dev_attempt = await client.post(f"{plan_url}/admin-approvals", json=body, headers=dev)
        after_dev_attempt = await state.events.read_after(project_id, 0)

        done = asyncio.create_task(
            _wait_for(state.events, project_id, "card", "state", "succeeded")
        )
        await asyncio.sleep(0)
        admin_approval = await client.post(f"{plan_url}/admin-approvals", json=body, headers=admin)
        await done
    return S10Run(
        state,
        project_id,
        card.plan_id,  # type: ignore[union-attr, arg-type]
        after_plan,
        dev_validation_attempt,
        after_dev_validation_attempt,
        dev_approval,
        after_dev_approval,
        executions,
        dev_attempt,
        after_dev_attempt,
        admin_approval,
        await state.events.read_after(project_id, 0),
    )
