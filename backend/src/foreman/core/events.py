"""Événements du flux d'un projet : contrat figé v1 (voir docs/plans/semaine-1.md).

Règle d'évolution : un ajout (nouveau `type`, nouveau champ optionnel) garde `v: 1` ;
tout autre changement passe à `v: 2`. Le front ignore les types qu'il ne connaît pas.

Sémantique de `seq` : strictement croissant, contigu à partir de 1, par projet, livré dans l'ordre.
Une carte (`card`) remplace la précédente de même `card_id` ; un `execution_step` dont la carte
est inconnue est ignoré.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

StepStatus = Literal["pending", "running", "succeeded", "failed", "compensated", "skipped"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _EventBase(_Model):
    v: Literal[1] = 1
    seq: Annotated[
        int,
        Field(ge=1, description="Strictement croissant, contigu à partir de 1, par projet"),
    ]
    project_id: UUID
    turn_id: UUID
    at: Annotated[AwareDatetime, Field(description="Horodatage avec fuseau (UTC)")]


class MessageData(_Model):
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(max_length=8000)]


class CardStep(_Model):
    step: Annotated[int, Field(ge=1, description="Indice de l'étape dans la carte")]
    title: Annotated[str, Field(max_length=200)]
    status: StepStatus


class PlanCardData(_Model):
    card_id: Annotated[str, Field(max_length=64)]
    kind: Literal["plan"] = "plan"
    title: Annotated[str, Field(max_length=200)]
    summary: Annotated[str, Field(max_length=500)]
    steps: Annotated[list[CardStep], Field(max_length=20)]


class ExecutionStepData(_Model):
    card_id: Annotated[str, Field(max_length=64)]
    step: Annotated[int, Field(ge=1, description="Indice de l'étape dans la carte")]
    status: StepStatus


class TurnStatusData(_Model):
    status: Literal["running", "completed", "failed"]


ERROR_MESSAGES = {
    "internal_error": "Une erreur est survenue. Réessayez.",
    "unknown_tool": "L'agent a demandé une action qui n'existe pas.",
}


class ErrorData(_Model):
    code: Literal["internal_error", "unknown_tool"]
    message: Annotated[str, Field(description="Texte fixe dérivé de `code`, jamais une exception")]

    @model_validator(mode="after")
    def _message_is_the_fixed_text(self) -> "ErrorData":
        if self.message != ERROR_MESSAGES[self.code]:
            raise ValueError("message non conforme au code")
        return self


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
