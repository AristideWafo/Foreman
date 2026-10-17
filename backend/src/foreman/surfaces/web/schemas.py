"""Objets de requête et de réponse de l'API (contrat figé v1)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=120)] = ""


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=4000)]


class MessageAccepted(BaseModel):
    turn_id: UUID


ErrorCode = Literal[
    "not_found",
    "invalid_request",
    "method_not_allowed",
    "turn_in_progress",
    "capacity_exceeded",
    "internal_error",
    "not_implemented",
]


class ErrorResponse(BaseModel):
    """Erreur opaque : un code, jamais le détail d'une exception ni la saisie de l'utilisateur."""

    error: ErrorCode
