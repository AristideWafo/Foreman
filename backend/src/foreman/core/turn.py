"""Service de tour partagé par toutes les surfaces."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from foreman.core.events import (
    ERROR_MESSAGES,
    CardStep,
    ErrorData,
    EventData,
    MessageData,
    PlanCardData,
    TurnStatusData,
)
from foreman.core.ports import EventLog, Provider, ToolCall

logger = logging.getLogger(__name__)

FailureCode = Literal["internal_error", "unknown_tool"]

PROPOSE_PLAN = "propose_plan"
DEFAULT_PROVIDER_TIMEOUT_S = 60.0


@dataclass(frozen=True, slots=True)
class TurnRequest:
    user_id: str
    project_id: UUID
    message: str


class TurnInProgress(Exception):
    """Un tour est déjà en cours pour ce projet."""


class _PlanStepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=200)]


class ProposePlanArguments(BaseModel):
    """Arguments validés de l'outil `propose_plan` (le modèle n'est jamais cru sur parole)."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=200)]
    summary: Annotated[str, Field(max_length=500)]
    steps: Annotated[list[_PlanStepArgs], Field(min_length=1, max_length=20)]


class TurnService:
    """Point d'entrée unique de la logique d'agent (web, CLI et webhooks l'appellent).

    Un seul tour à la fois par projet : `begin` réserve le projet de façon synchrone (aucun
    `await`), donc deux appels concurrents ne peuvent pas tous deux réussir.
    """

    def __init__(
        self,
        provider: Provider,
        events: EventLog,
        provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
    ) -> None:
        self._provider = provider
        self._events = events
        self._provider_timeout_s = provider_timeout_s
        self._active: dict[UUID, UUID] = {}

    def begin(self, project_id: UUID) -> UUID:
        """Réserve le projet et renvoie l'identifiant du tour. Lève `TurnInProgress`."""
        if project_id in self._active:
            raise TurnInProgress
        turn_id = uuid4()
        self._active[project_id] = turn_id
        return turn_id

    def release(self, project_id: UUID, turn_id: UUID) -> None:
        if self._active.get(project_id) == turn_id:
            del self._active[project_id]

    async def run(self, request: TurnRequest, turn_id: UUID) -> None:
        """Joue le tour réservé par `begin`. Ne lève jamais : un échec devient un événement."""
        try:
            await self._run(request, turn_id)
        except Exception:
            logger.exception("turn_crashed project=%s turn=%s", request.project_id, turn_id)
            try:
                await self._fail(request.project_id, turn_id, "internal_error")
            except Exception:
                logger.exception("turn_failure_not_recorded turn=%s", turn_id)
        finally:
            self.release(request.project_id, turn_id)

    async def _emit(self, project_id: UUID, turn_id: UUID, data: EventData) -> None:
        await self._events.append(project_id, turn_id, data)

    async def _fail(self, project_id: UUID, turn_id: UUID, code: FailureCode) -> None:
        await self._emit(project_id, turn_id, ErrorData(code=code, message=ERROR_MESSAGES[code]))
        await self._emit(project_id, turn_id, TurnStatusData(status="failed"))

    async def _run(self, request: TurnRequest, turn_id: UUID) -> None:
        project_id = request.project_id
        await self._emit(project_id, turn_id, MessageData(role="user", text=request.message))
        await self._emit(project_id, turn_id, TurnStatusData(status="running"))
        try:
            # Délai explicite : sinon un fournisseur muet bloque le projet en 409 pour toujours.
            async with asyncio.timeout(self._provider_timeout_s):
                reply = await self._provider.complete([request.message])
        except Exception:
            logger.exception("provider_failed project=%s turn=%s", project_id, turn_id)
            await self._fail(project_id, turn_id, "internal_error")
            return
        await self._emit(project_id, turn_id, MessageData(role="assistant", text=reply.text))
        for call in reply.tool_calls:
            failure = await self._apply(project_id, turn_id, call)
            if failure is not None:
                await self._fail(project_id, turn_id, failure)
                return
        await self._emit(project_id, turn_id, TurnStatusData(status="completed"))

    async def _apply(self, project_id: UUID, turn_id: UUID, call: ToolCall) -> FailureCode | None:
        """Code d'erreur ou `None`. Seul `propose_plan` existe ; aucun autre outil ne s'exécute."""
        if call.name != PROPOSE_PLAN:
            logger.warning("unknown_tool project=%s turn=%s", project_id, turn_id)
            return "unknown_tool"
        try:
            plan = ProposePlanArguments.model_validate(call.arguments)
        except ValidationError:
            logger.warning("invalid_plan project=%s turn=%s", project_id, turn_id)
            return "internal_error"
        card = PlanCardData(
            card_id=uuid4().hex,
            kind="plan",
            title=plan.title,
            summary=plan.summary,
            steps=[
                CardStep(step=i, title=step.title, status="pending")
                for i, step in enumerate(plan.steps, start=1)
            ],
        )
        await self._emit(project_id, turn_id, card)
        return None
