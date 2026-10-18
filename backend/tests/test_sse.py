"""Flux SSE de bout en bout : vrai serveur uvicorn sur un port libre, client httpx en flux."""

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import pytest
import uvicorn

from foreman.bootstrap.configure import App, Profile
from foreman.core.events import MessageData
from foreman.core.ports import Provider
from foreman.core.turn import TurnService
from foreman.infra.file_catalog import catalog_dir_from_env
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.replay_provider import ReplayProvider
from foreman.surfaces.web.app import create_app

TIMEOUT = 10  # filet de sécurité : jamais atteint quand tout fonctionne


@dataclass
class Frame:
    id: str | None = None
    retry: str | None = None
    data: dict[str, Any] | None = None
    comments: list[str] = field(default_factory=list)


@dataclass
class Server:
    base_url: str
    log: InMemoryEventLog
    projects: InMemoryProjectStore
    turns: TurnService

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=TIMEOUT)

    async def new_project(self, client: httpx.AsyncClient) -> UUID:
        return UUID((await client.post("/api/projects")).json()["id"])


async def serve(
    provider: Provider, queue_size: int | None = None, max_subscribers_per_project: int = 20
) -> AsyncIterator[Server]:
    log = InMemoryEventLog(
        queue_size=queue_size or 100, max_subscribers_per_project=max_subscribers_per_project
    )
    projects = InMemoryProjectStore()
    turns = TurnService(provider, log)
    app = create_app(App(profile=Profile.WEB, projects=projects, events=log, turns=turns))
    # Socket réservé avant le démarrage : les connexions attendent dans le backlog, sans sondage.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]), name="uvicorn-test")
    try:
        yield Server(f"http://127.0.0.1:{sock.getsockname()[1]}", log, projects, turns)
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=TIMEOUT)
        sock.close()


@pytest.fixture
async def server() -> AsyncIterator[Server]:
    async for s in serve(ReplayProvider.s01(catalog_dir_from_env())):
        yield s


async def read_frames(response: httpx.Response) -> AsyncIterator[Frame]:
    """Découpe le flux en trames (séparées par une ligne vide), commentaires à part."""
    frame, started = Frame(), False
    async for line in response.aiter_lines():
        if line == "":
            if started:
                yield frame
            frame, started = Frame(), False
            continue
        started = True
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "":
            frame.comments.append(value)
        elif name == "id":
            frame.id = value
        elif name == "retry":
            frame.retry = value
        elif name == "data":
            frame.data = json.loads(value)


async def event_frames(response: httpx.Response) -> AsyncIterator[Frame]:
    async for frame in read_frames(response):
        if frame.data is not None:
            yield frame


async def collect_until_completed(response: httpx.Response) -> list[Frame]:
    frames: list[Frame] = []
    async with asyncio.timeout(TIMEOUT):
        async for frame in event_frames(response):
            frames.append(frame)
            assert frame.data is not None
            if frame.data["type"] == "turn_status" and frame.data["data"]["status"] == "completed":
                break
    return frames


async def test_a_turn_is_streamed_end_to_end_and_the_card_is_read(server: Server) -> None:
    async with server.client() as client:
        project_id = await server.new_project(client)
        async with client.stream("GET", f"/api/projects/{project_id}/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-cache"
            assert response.headers["x-accel-buffering"] == "no"
            await server.log.wait_for_subscriber_count(project_id, 1)
            posted = await client.post(
                f"/api/projects/{project_id}/messages", json={"text": "Crée Safe Eat"}
            )
            assert posted.status_code == 202
            frames = await collect_until_completed(response)

    assert [f.data["type"] for f in frames if f.data] == [
        "message",
        "turn_status",
        "message",
        "card",
        "turn_status",
    ]
    assert [f.id for f in frames] == ["1", "2", "3", "4", "5"]
    assert all(f.retry == "3000" for f in frames)
    assert all(f.data is not None and "event" not in f.data for f in frames)
    card = frames[3].data
    assert card is not None
    assert card["data"]["kind"] == "plan"
    assert [s["status"] for s in card["data"]["steps"]] == ["pending"] * 7
    assert card["turn_id"] == posted.json()["turn_id"]


async def test_headers_arrive_before_any_business_event(server: Server) -> None:
    """Le front poste son message à `onopen` : la réponse 200 ne peut pas attendre un événement."""
    async with server.client() as client:
        project_id = await server.new_project(client)
        # Aucun événement publié : si les en-têtes attendaient le premier événement, ce bloc
        # n'obtiendrait jamais la réponse et le délai expirerait.
        async with asyncio.timeout(TIMEOUT):
            async with client.stream("GET", f"/api/projects/{project_id}/events") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
        assert await server.log.read_after(project_id, 0) == []


async def test_an_idle_stream_sends_keepalive_comments(
    server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("foreman.surfaces.web.api.KEEPALIVE_SECONDS", 0.01)
    async with server.client() as client:
        project_id = await server.new_project(client)
        async with client.stream("GET", f"/api/projects/{project_id}/events") as response:
            async with asyncio.timeout(TIMEOUT):
                async for frame in read_frames(response):
                    if frame.comments:
                        break
    assert frame.comments == ["ping"]
    assert frame.data is None


async def test_the_stream_announces_the_retry_delay_before_any_event(server: Server) -> None:
    async with server.client() as client:
        project_id = await server.new_project(client)
        async with client.stream("GET", f"/api/projects/{project_id}/events") as response:
            async with asyncio.timeout(TIMEOUT):
                first = await anext(read_frames(response))
    assert first.retry == "3000"
    assert first.data is None


async def test_resume_with_last_event_id_has_no_gap_and_no_duplicate(server: Server) -> None:
    async with server.client() as client:
        project_id = await server.new_project(client)
        url = f"/api/projects/{project_id}"
        await client.post(f"{url}/messages", json={"text": "un"})
        async with client.stream("GET", f"{url}/events") as response:
            first = await collect_until_completed(response)
        assert [f.id for f in first] == ["1", "2", "3", "4", "5"]

        # Le client a vu jusqu'à seq 3 ; un second tour se produit pendant la reprise.
        async with client.stream("GET", f"{url}/events", headers={"Last-Event-ID": "3"}) as r:
            await server.log.wait_for_subscriber_count(project_id, 1)
            assert (await client.post(f"{url}/messages", json={"text": "deux"})).status_code == 202
            seen: list[int] = []
            async with asyncio.timeout(TIMEOUT):
                async for frame in event_frames(r):
                    assert frame.data is not None
                    seen.append(frame.data["seq"])
                    if seen[-1] == 10:
                        break
    assert seen == [4, 5, 6, 7, 8, 9, 10]


async def test_resume_uses_the_larger_of_last_event_id_and_after_and_garbage_is_ignored(
    server: Server,
) -> None:
    async with server.client() as client:
        project_id = await server.new_project(client)
        url = f"/api/projects/{project_id}"
        await client.post(f"{url}/messages", json={"text": "un"})
        async with client.stream("GET", f"{url}/events") as response:
            await collect_until_completed(response)

        async def first_seq(query: str, headers: dict[str, str]) -> int:
            async with client.stream("GET", f"{url}/events{query}", headers=headers) as r:
                async with asyncio.timeout(TIMEOUT):
                    async for frame in event_frames(r):
                        assert frame.data is not None
                        return int(frame.data["seq"])
            raise AssertionError("aucun événement")

        assert await first_seq("?after=1", {}) == 2
        assert await first_seq("?after=1", {"Last-Event-ID": "3"}) == 4
        assert await first_seq("?after=4", {"Last-Event-ID": "2"}) == 5
        assert await first_seq("", {"Last-Event-ID": "pas-un-nombre"}) == 1


async def test_unknown_project_is_an_opaque_404(server: Server) -> None:
    async with server.client() as client:
        response = await client.get("/api/projects/00000000-0000-4000-8000-000000000000/events")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


async def test_subscribers_are_removed_when_the_client_disconnects(server: Server) -> None:
    async with server.client() as client:
        project_id = await server.new_project(client)
        async with client.stream("GET", f"/api/projects/{project_id}/events") as response:
            await server.log.wait_for_subscriber_count(project_id, 1)
            assert response.status_code == 200
        # La sortie du bloc ferme la connexion : le serveur doit retirer l'abonné.
        await asyncio.wait_for(server.log.wait_for_subscriber_count(project_id, 0), TIMEOUT)
    assert server.log.subscriber_count(project_id) == 0


class NoProvider:
    async def complete(self, messages: Sequence[str]) -> Any:
        raise AssertionError("aucun tour dans ce test")


async def test_a_slow_subscriber_is_cut_by_the_server_and_resumes_without_gap() -> None:
    async for server in serve(NoProvider(), queue_size=3):
        async with server.client() as client:
            project_id = await server.new_project(client)
            url = f"/api/projects/{project_id}/events"
            turn_id = UUID(int=1)
            async with client.stream("GET", url) as response:
                frames = read_frames(response)
                async with asyncio.timeout(TIMEOUT):
                    await anext(frames)  # annonce de retry : le générateur est en cours
                    await server.log.wait_for_subscriber_count(project_id, 1)
                    # Sans rien lire entre-temps : la file (3) déborde, le serveur coupe le flux.
                    for i in range(10):
                        await server.log.append(
                            project_id, turn_id, MessageData(role="user", text=str(i))
                        )
                    await server.log.wait_for_subscriber_count(project_id, 0)
                    # Le flux se termine de lui-même : c'est le serveur qui l'a fermé.
                    received = [f.data["seq"] async for f in data_frames(frames) if f.data]
            # Le client reprend là où il s'est arrêté : aucun trou, aucun doublon.
            last = received[-1] if received else 0
            async with client.stream("GET", url, headers={"Last-Event-ID": str(last)}) as again:
                async with asyncio.timeout(TIMEOUT):
                    rest: list[int] = []
                    async for f in data_frames(read_frames(again)):
                        assert f.data is not None
                        rest.append(f.data["seq"])
                        if len(received) + len(rest) == 10:
                            break
            assert received + rest == list(range(1, 11))


async def data_frames(frames: AsyncIterator[Frame]) -> AsyncIterator[Frame]:
    async for frame in frames:
        if frame.data is not None:
            yield frame


async def test_too_many_streams_on_a_project_get_an_opaque_503() -> None:
    async for server in serve(
        ReplayProvider.s01(catalog_dir_from_env()), max_subscribers_per_project=2
    ):
        async with server.client() as client:
            project = await server.new_project(client)
            url = f"/api/projects/{project}/events"
            async with client.stream("GET", url) as one, client.stream("GET", url) as two:
                assert one.status_code == two.status_code == 200
                await server.log.wait_for_subscriber_count(project, 2)
                refused = await client.get(url)
                assert refused.status_code == 503
                assert refused.json() == {"error": "capacity_exceeded"}
            await server.log.wait_for_subscriber_count(project, 0)
            async with client.stream("GET", url) as again:
                assert again.status_code == 200  # un emplacement libéré est réutilisable


async def test_an_absurdly_long_last_event_id_is_ignored_not_a_500() -> None:
    async for server in serve(ReplayProvider.s01(catalog_dir_from_env())):
        async with server.client() as client:
            project = await server.new_project(client)
            url = f"/api/projects/{project}/events"
            async with client.stream("GET", url, headers={"Last-Event-ID": "9" * 5000}) as r:
                assert r.status_code == 200
