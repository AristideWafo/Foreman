"""Routes de l'API (contrat figé v1)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from foreman.bootstrap.configure import App
from foreman.core.events import AnyEvent
from foreman.core.ports import CapacityExceeded
from foreman.core.projects import Project
from foreman.core.turn import TurnInProgress, TurnRequest
from foreman.surfaces.web.errors import ApiError
from foreman.surfaces.web.schemas import (
    CreateProjectRequest,
    ErrorResponse,
    MessageAccepted,
    MessageRequest,
)
from foreman.surfaces.web.tasks import TaskRegistry

WEB_USER_ID = "web-anonymous"  # semaine 1 : aucune identité (authentification en S10)

_ERRORS: dict[int | str, dict[str, Any]] = {
    # Descriptions explicites : la bibliothèque standard les libelle différemment selon la version
    # de Python, ce qui ferait varier openapi.json entre le poste et la CI.
    404: {"model": ErrorResponse, "description": "Introuvable"},
    422: {"model": ErrorResponse, "description": "Requête invalide"},
    501: {"model": ErrorResponse, "description": "Pas encore implémenté"},
    503: {"model": ErrorResponse, "description": "Capacité atteinte"},
}


_SSE_DESCRIPTION = (
    "Flux SSE. `id:` = `seq`, pas de champ `event:`, `data:` = un `Event` JSON, commentaire `:` "
    "de maintien toutes les 15 s, `retry: 3000`. Rejoue les événements de "
    "`seq > max(Last-Event-ID, after)`, dans l'ordre, puis le direct. Un `Last-Event-ID` non "
    "numérique est ignoré. Si la reprise est plus ancienne que le plus vieil événement "
    "conservé, le serveur rejoue depuis celui-ci (le client détecte le trou par la rupture de "
    "contiguïté de `seq` et repart de l'état reçu). Un abonné trop lent voit le flux fermé par "
    "le serveur et se reconnecte. Toute réponse non 200 est invisible pour `EventSource` : sur "
    "erreur avec `readyState` à `CLOSED`, appeler `GET /projects/{id}` pour distinguer 404 et 503."
)


RETRY_MS = 3000  # délai de reconnexion annoncé à EventSource


def _parse_last_event_id(value: str | None) -> int:
    """Un `Last-Event-ID` absent ou non numérique est ignoré (reprise depuis `after`)."""
    # 19 chiffres au plus : au-delà, `int()` coûte cher et la valeur n'a aucun sens (ignorée).
    if value is not None and value.isascii() and value.isdecimal() and len(value) <= 19:
        return int(value)
    return 0


KEEPALIVE_SECONDS = 15.0  # commentaire de maintien (utile derrière Traefik)


class EventStreamResponse(StreamingResponse):
    """Réponse `text/event-stream` (OpenAPI : seul ce type de contenu est déclaré)."""

    media_type = "text/event-stream"


def _frame(event: AnyEvent) -> bytes:
    """`id:` = seq, pas de champ `event:`, `data:` = l'enveloppe JSON (une seule ligne)."""
    return f"id: {event.seq}\nretry: {RETRY_MS}\ndata: {event.model_dump_json()}\n\n".encode()


def create_router(app: App, tasks: TaskRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/projects", status_code=201, response_model=Project, responses=_ERRORS)
    async def create_project(body: CreateProjectRequest | None = None) -> Project:
        """Crée un projet. Le corps est facultatif (`title` vaut alors une chaîne vide)."""
        try:
            return await app.projects.create(body.title if body else "")
        except CapacityExceeded:
            raise ApiError(503, "capacity_exceeded") from None

    @router.get("/projects/{project_id}", response_model=Project, responses=_ERRORS)
    async def get_project(project_id: UUID) -> Project:
        project = await app.projects.get(project_id)
        if project is None:
            raise ApiError(404, "not_found")
        return project

    @router.post(
        "/projects/{project_id}/messages",
        status_code=202,
        response_model=MessageAccepted,
        responses={
            **_ERRORS,
            409: {
                "model": ErrorResponse,
                "description": "Un tour est déjà en cours pour ce projet (`turn_in_progress`)",
            },
        },
    )
    async def post_message(project_id: UUID, body: MessageRequest) -> MessageAccepted:
        """Un seul tour à la fois par projet : un second message pendant un tour renvoie 409."""
        if await app.projects.get(project_id) is None:
            raise ApiError(404, "not_found")
        try:
            turn_id = app.turns.begin(project_id)
        except TurnInProgress:
            raise ApiError(409, "turn_in_progress") from None
        request = TurnRequest(user_id=WEB_USER_ID, project_id=project_id, message=body.text)
        try:
            tasks.spawn(app.turns.run(request, turn_id))
        except BaseException:
            app.turns.release(project_id, turn_id)
            raise
        return MessageAccepted(turn_id=turn_id)

    async def stream(project_id: UUID, cursor: int) -> AsyncIterator[bytes]:
        # Inscription AVANT la lecture de l'historique : aucun trou entre le rejeu et le direct.
        try:
            subscription = app.events.subscribe(project_id)
        except CapacityExceeded:
            return  # plafond atteint entre le contrôle de la route et l'ouverture du flux
        try:
            # Écrit tout de suite : les en-têtes partent avant le premier événement métier.
            yield f"retry: {RETRY_MS}\n\n".encode()
            for event in await app.events.read_after(project_id, cursor):
                cursor = event.seq
                yield _frame(event)
            # Un événement déjà rejoué peut aussi se trouver dans la file : on l'ignore (seq).
            while True:
                try:
                    live = await asyncio.wait_for(subscription.next(), KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                if live is None:
                    return
                if live.seq > cursor:
                    cursor = live.seq
                    yield _frame(live)
        finally:
            subscription.close()

    @router.get(
        "/projects/{project_id}/events",
        response_class=EventStreamResponse,
        responses={
            200: {
                "description": _SSE_DESCRIPTION,
                "content": {
                    "text/event-stream": {"schema": {"$ref": "#/components/schemas/Event"}}
                },
            },
            **_ERRORS,
        },
    )
    async def stream_events(
        project_id: UUID,
        after: Annotated[int, Query(ge=0)] = 0,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> EventStreamResponse:
        if await app.projects.get(project_id) is None:
            raise ApiError(404, "not_found")
        if not app.events.has_subscriber_capacity(project_id):
            raise ApiError(503, "capacity_exceeded")
        cursor = max(after, _parse_last_event_id(last_event_id))
        return EventStreamResponse(
            stream(project_id, cursor),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
