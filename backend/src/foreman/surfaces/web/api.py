"""Routes de l'API (contrat figé v1). Les corps sont implémentés par les PR suivantes."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse, StreamingResponse

from foreman.core.projects import Project
from foreman.surfaces.web.errors import error_response
from foreman.surfaces.web.schemas import (
    CreateProjectRequest,
    ErrorResponse,
    MessageAccepted,
    MessageRequest,
)

router = APIRouter(prefix="/api")

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


class EventStreamResponse(StreamingResponse):
    """Réponse `text/event-stream` (documentation OpenAPI : seul ce type de contenu est déclaré)."""

    media_type = "text/event-stream"


def _not_implemented() -> JSONResponse:
    return error_response(501, "not_implemented")


@router.post("/projects", status_code=201, response_model=Project, responses=_ERRORS)
async def create_project(body: CreateProjectRequest | None = None) -> JSONResponse:
    """Crée un projet. Le corps est facultatif (`title` vaut alors une chaîne vide)."""
    return _not_implemented()


@router.get("/projects/{project_id}", response_model=Project, responses=_ERRORS)
async def get_project(project_id: UUID) -> JSONResponse:
    return _not_implemented()


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
async def post_message(project_id: UUID, body: MessageRequest) -> JSONResponse:
    """Un seul tour à la fois par projet : un second message pendant un tour renvoie 409."""
    return _not_implemented()


@router.get(
    "/projects/{project_id}/events",
    response_class=EventStreamResponse,
    responses={
        200: {
            "description": _SSE_DESCRIPTION,
            "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/Event"}}},
        },
        **_ERRORS,
    },
)
async def stream_events(
    project_id: UUID,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    return _not_implemented()
