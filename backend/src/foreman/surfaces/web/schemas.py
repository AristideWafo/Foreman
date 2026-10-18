"""Objets de requête et de réponse de l'API (contrat figé v1)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from foreman.core.events import (
    Budget,
    ExecutionResult,
    ExecutionState,
    PlanStatus,
    ResourceRef,
    Sha256,
    StepStatus,
)


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
    "plan_hash_mismatch",
    "plan_not_approvable",
    "execution_in_progress",
    "question_closed",
]


class ErrorResponse(BaseModel):
    """Erreur opaque : un code, jamais le détail d'une exception ni la saisie de l'utilisateur."""

    error: ErrorCode


class QuestionAnswerRequest(BaseModel):
    """Réponse à une question de clarification, ou report (`defer`)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["answer", "defer"]
    value: Annotated[str | None, Field(min_length=1, max_length=500)] = None

    @model_validator(mode="after")
    def _answer_needs_a_value(self) -> "QuestionAnswerRequest":
        if self.decision == "answer" and self.value is None:
            raise ValueError("value requis pour answer")
        return self


class QuestionAccepted(BaseModel):
    question_id: Annotated[str, Field(max_length=64)]
    status: Literal["answered", "deferred"]


class ApprovalRequest(BaseModel):
    """Approbation d'un plan : elle porte sur le HASH affiché, pas sur « le dernier plan »."""

    model_config = ConfigDict(extra="forbid")

    plan_hash: Sha256
    decision: Literal["approved"]


class ApprovalAccepted(BaseModel):
    approval_id: UUID
    execution_id: UUID


class PlanView(BaseModel):
    id: UUID
    version: Annotated[int, Field(ge=1)]
    status: PlanStatus
    content_hash: Sha256
    content: Annotated[dict[str, JsonValue], Field(description="Contenu canonique haché du plan")]
    created_at: AwareDatetime
    expires_at: AwareDatetime


class ExecutionStepView(BaseModel):
    step: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(max_length=200)]
    tool: Annotated[str, Field(max_length=100)]
    status: StepStatus
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class ExecutionView(BaseModel):
    id: UUID
    plan_id: UUID
    plan_card_id: Annotated[str | None, Field(max_length=100)] = None
    state: ExecutionState
    autonomy_level: Annotated[int, Field(ge=1, le=4)]
    budget: Budget
    steps: Annotated[list[ExecutionStepView], Field(max_length=20)]
    resources: Annotated[list[ResourceRef], Field(max_length=50)]
    result: ExecutionResult | None = None
