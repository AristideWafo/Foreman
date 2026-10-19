"""Le scénario S12 (plan invalidé : projet ou catalogue modifié, plan échu), en mémoire.

Partagé par le test e2e et l'export du fixture du front (`make s12-fixture`). Le modèle rejoue
`s01.yaml` (S1) ou `s10.yaml` (production) ; l'horloge est injectée dans les services, et le
« redéploiement » reconstruit les services sur les MÊMES dépôts et le même journal.
"""

import asyncio
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from s01_run import BASE_TIME, USER_MESSAGE, _wait_for
from s10_run import USER_MESSAGE as PROD_MESSAGE

from foreman.bootstrap.adapters import build_gateway
from foreman.bootstrap.configure import App, Profile, configure
from foreman.core.approval import ApprovalService
from foreman.core.catalog import Catalog
from foreman.core.events import AnyEvent
from foreman.core.execution.engine import ExecutionEngine
from foreman.core.planning import Planner
from foreman.core.turn import TurnService
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.replay_provider import ReplayProvider
from foreman.surfaces.web.app import create_app

HEADERS_DEV, HEADERS_ADMIN = {"X-Forwarded-User": "dev"}, {"X-Forwarded-User": "admin"}


class Clock:
    """Horloge manuelle : le temps ne passe que par `advance`."""

    def __init__(self) -> None:
        self.now = BASE_TIME

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


def redeploy(state: App, catalog: Catalog, clock: Callable[[], datetime]) -> App:
    """Services reconstruits sur le catalogue donné ; dépôts, journal et membres sont conservés."""
    gateway = build_gateway(catalog, state.stores, state.members)
    provider = ReplayProvider.from_dir(catalog_dir_from_env())
    planner = Planner(catalog, state.stores.plans, state.stores.registry, clock)
    return replace(
        state,
        catalog=catalog,
        gateway=gateway,
        turns=TurnService(provider, state.events, planner, state.projects),
        approvals=ApprovalService(catalog, state.stores, state.events, state.members, clock),
        engine=ExecutionEngine(
            catalog=catalog, stores=state.stores, gateway=gateway, events=state.events
        ),
    )


def client_for(state: App) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(state)), base_url="http://test"
    )


async def propose(
    client: httpx.AsyncClient, state: App, project_id: UUID, text: str, headers: dict[str, str]
) -> Any:
    """Un message, puis la carte plan proposée (la dernière du flux)."""
    planned = asyncio.create_task(
        _wait_for(state.events, project_id, "turn_status", "status", "completed")
    )
    await asyncio.sleep(0)  # l'abonnement précède le message
    await client.post(f"/api/projects/{project_id}/messages", json={"text": text}, headers=headers)
    await planned
    cards = [e.data for e in await state.events.read_after(project_id, 0) if e.type == "card"]
    return [c for c in cards if c.kind == "plan"][-1]


async def decide(
    client: httpx.AsyncClient, project_id: UUID, card: Any, headers: dict[str, str], admin: bool
) -> httpx.Response:
    route = "admin-approvals" if admin else "approvals"
    return await client.post(
        f"/api/projects/{project_id}/plans/{card.plan_id}/{route}",
        json={"plan_hash": card.plan_hash, "decision": "approved"},
        headers=headers,
    )


async def approve_and_wait(
    client: httpx.AsyncClient, state: App, project_id: UUID, card: Any
) -> httpx.Response:
    done = asyncio.create_task(_wait_for(state.events, project_id, "card", "state", "succeeded"))
    await asyncio.sleep(0)
    response = await decide(client, project_id, card, {}, admin=False)
    if response.status_code == 201:
        await done
    else:
        done.cancel()
    return response


@dataclass(frozen=True)
class ProjectChanged:
    state: App
    project_id: UUID
    v1: Any
    v2: Any
    v3: Any
    v2_response: httpx.Response
    v1_response: httpx.Response
    v3_response: httpx.Response
    events_before_v1: list[AnyEvent]  # flux avant la validation périmée
    events: list[AnyEvent]


async def run_project_changed() -> ProjectChanged:
    initial = configure(Profile.WEB)
    state = redeploy(initial, initial.catalog, Clock())  # type: ignore[arg-type]
    async with client_for(state) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        v1 = await propose(client, state, project_id, USER_MESSAGE, {})
        v2 = await propose(client, state, project_id, USER_MESSAGE, {})
        v2_response = await approve_and_wait(client, state, project_id, v2)
        before = await state.events.read_after(project_id, 0)
        v1_response = await decide(client, project_id, v1, {}, admin=False)
        v3 = await propose(client, state, project_id, USER_MESSAGE, {})
        v3_response = await approve_and_wait(client, state, project_id, v3)
    events = await state.events.read_after(project_id, 0)
    return ProjectChanged(
        state, project_id, v1, v2, v3, v2_response, v1_response, v3_response, before, events
    )


@dataclass(frozen=True)
class CatalogChanged:
    state: App
    project_id: UUID
    plan: Any
    dev_response: httpx.Response
    admin_response: httpx.Response
    events: list[AnyEvent]


def _changed_catalog(tmp_path: Path) -> Catalog:
    """Copie du catalogue dont un référentiel diffère d'un octet (l'empreinte change)."""
    copy = tmp_path / "catalog"
    shutil.copytree(catalog_dir_from_env(), copy)
    with (copy / "referentiels" / "infra-staging.yaml").open("a", encoding="utf-8") as f:
        f.write("\n")
    return load_catalog(copy, environment=os.environ.get("FOREMAN_ENVIRONMENT", "staging"))


async def run_catalog_changed(tmp_path: Path) -> CatalogChanged:
    os.environ["FOREMAN_AUTH_MODE"] = "proxy_header"
    os.environ["FOREMAN_DEV_MEMBERS"] = "dev:developer,admin:team_admin"
    try:
        initial = configure(Profile.WEB)
    finally:
        del os.environ["FOREMAN_AUTH_MODE"], os.environ["FOREMAN_DEV_MEMBERS"]
    clock = Clock()
    state = redeploy(initial, initial.catalog, clock)  # type: ignore[arg-type]
    async with client_for(state) as client:
        project_id = UUID(
            (
                await client.post("/api/projects", json={"title": "Safe Eat"}, headers=HEADERS_DEV)
            ).json()["id"]
        )
        plan = await propose(client, state, project_id, PROD_MESSAGE, HEADERS_DEV)
        dev_response = await decide(client, project_id, plan, HEADERS_DEV, admin=False)
    state = redeploy(state, _changed_catalog(tmp_path), clock)  # le référentiel a changé
    async with client_for(state) as client:
        admin_response = await decide(client, project_id, plan, HEADERS_ADMIN, admin=True)
    events = await state.events.read_after(project_id, 0)
    return CatalogChanged(state, project_id, plan, dev_response, admin_response, events)


@dataclass(frozen=True)
class Expired:
    state: App
    project_id: UUID
    plan: Any
    swept: list[Any]  # plans passés `expired` par le dépôt
    status: str
    response: httpx.Response
    events: list[AnyEvent]


async def run_expired() -> Expired:
    initial = configure(Profile.WEB)
    clock = Clock()
    state = redeploy(initial, initial.catalog, clock)  # type: ignore[arg-type]
    async with client_for(state) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        plan = await propose(client, state, project_id, USER_MESSAGE, {})
        clock.advance(timedelta(hours=24, seconds=1))
        swept = await state.stores.plans.expire_due(clock())
        record = await state.stores.plans.get(project_id, plan.plan_id)
        response = await decide(client, project_id, plan, {}, admin=False)
        await decide(client, project_id, plan, {}, admin=False)  # rejeu : aucune carte de plus
    events = await state.events.read_after(project_id, 0)
    return Expired(state, project_id, plan, swept, record.status, response, events)  # type: ignore[union-attr]
