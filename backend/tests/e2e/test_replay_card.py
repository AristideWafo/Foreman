"""Rejeu de la même demande : exécution réussie, carte avec les ressources déjà présentes."""

import asyncio
from uuid import UUID

import httpx
import pytest
from s01_run import ADMIN_HEADERS, DEV_HEADERS, USER_MESSAGE, _wait_for, configure_web

from foreman.surfaces.web.app import create_app


@pytest.fixture(autouse=True)
def in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FOREMAN_DATABASE_URL", raising=False)


async def test_a_replayed_request_succeeds_and_its_card_lists_the_existing_resources() -> None:
    state = configure_web()
    transport = httpx.ASGITransport(app=create_app(state))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=DEV_HEADERS
    ) as client:
        project_id = UUID(
            (await client.post("/api/projects", json={"title": "Safe Eat"})).json()["id"]
        )
        for _ in range(2):
            planned = asyncio.create_task(
                _wait_for(state.events, project_id, "turn_status", "status", "completed")
            )
            await asyncio.sleep(0)
            await client.post(f"/api/projects/{project_id}/messages", json={"text": USER_MESSAGE})
            await planned
            card = [
                e.data
                for e in await state.events.read_after(project_id, 0)
                if e.type == "card" and e.data.kind == "plan" and e.data.status == "proposed"  # type: ignore[union-attr]
            ][-1]
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
    registry = await state.stores.registry.list_for_project(project_id)
    assert len(registry) == 6  # aucune ressource en double au rejeu
    final = [
        e.data
        for e in await state.events.read_after(project_id, 0)
        if e.type == "card" and e.data.kind == "execution"  # type: ignore[union-attr]
    ][-1]
    assert final.state == "succeeded" and len(final.resources) == 6  # type: ignore[union-attr]
    assert all(r.reused for r in final.resources)  # type: ignore[union-attr]
    assert "6 ressources déjà présentes, aucune créée" in final.result.summary  # type: ignore[union-attr]
    # Chaque ressource désigne une étape réussie, ciblée par une ressource attendue du plan.
    plan = card  # type: ignore[possibly-undefined]
    succeeded = {s.step for s in final.steps if s.status == "succeeded"}  # type: ignore[union-attr]
    expected = {r.step for r in plan.expected_resources}  # type: ignore[union-attr]
    assert all(r.step in succeeded & expected for r in final.resources)  # type: ignore[union-attr]
