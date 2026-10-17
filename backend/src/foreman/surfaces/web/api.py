"""Routes de l'API (contrat figé v1). Les corps sont implémentés par les PR suivantes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


def _not_implemented() -> JSONResponse:
    return error_response(501, "not_implemented")


@router.post("/projects", status_code=201, response_model=Project, responses=_ERRORS)
async def create_project(body: CreateProjectRequest) -> JSONResponse:
    return _not_implemented()


@router.get("/projects/{project_id}", response_model=Project, responses=_ERRORS)
async def get_project(project_id: UUID) -> JSONResponse:
    return _not_implemented()


@router.post(
    "/projects/{project_id}/messages",
    status_code=202,
    response_model=MessageAccepted,
    responses=_ERRORS,
)
async def post_message(project_id: UUID, body: MessageRequest) -> JSONResponse:
    return _not_implemented()


@router.get(
    "/projects/{project_id}/events",
    responses={
        200: {
            "description": (
                "Flux SSE. `id:` = `seq`, pas de champ `event:`, `data:` = un `Event` JSON. "
                "Reprise : en-tête `Last-Event-ID` (prioritaire) ou paramètre `after`."
            ),
            "content": {"text/event-stream": {"schema": {"$ref": "#/components/schemas/Event"}}},
        },
        **_ERRORS,
    },
)
async def stream_events(project_id: UUID, after: int = 0) -> JSONResponse:
    return _not_implemented()
