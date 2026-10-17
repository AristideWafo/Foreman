"""Événements du flux d'un projet : contrat figé v1 (voir docs/plans/semaine-1.md).

Règle d'évolution : un ajout (nouveau `type`, nouveau champ optionnel) garde `v: 1` ;
tout autre changement passe à `v: 2`. Le front ignore les types qu'il ne connaît pas.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

StepStatus = Literal["pending", "running", "succeeded", "failed", "compensated", "skipped"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _EventBase(_Model):
    v: Literal[1] = 1
    seq: Annotated[int, Field(ge=1, description="Croissant, par projet")]
    project_id: UUID
    turn_id: UUID
    at: datetime


class MessageData(_Model):
    role: Literal["user", "assistant"]
    text: str


class CardStep(_Model):
    seq: int
    title: str
    status: StepStatus


class PlanCardData(_Model):
    card_id: str
    kind: Literal["plan"] = "plan"
    title: str
    summary: str
    steps: list[CardStep]


class ExecutionStepData(_Model):
    card_id: str
    seq: int
    status: StepStatus


class TurnStatusData(_Model):
    status: Literal["running", "completed", "failed"]


class ErrorData(_Model):
    code: Literal["internal_error", "unknown_tool"]
    message: Annotated[str, Field(description="Texte générique, jamais le détail d'une exception")]


class MessageEvent(_EventBase):
    type: Literal["message"] = "message"
    data: MessageData


class CardEvent(_EventBase):
    type: Literal["card"] = "card"
    data: PlanCardData


class ExecutionStepEvent(_EventBase):
    type: Literal["execution_step"] = "execution_step"
    data: ExecutionStepData


class TurnStatusEvent(_EventBase):
    type: Literal["turn_status"] = "turn_status"
    data: TurnStatusData


class ErrorEvent(_EventBase):
    type: Literal["error"] = "error"
    data: ErrorData


Event = Annotated[
    MessageEvent | CardEvent | ExecutionStepEvent | TurnStatusEvent | ErrorEvent,
    Field(discriminator="type"),
]
