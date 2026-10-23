"""Service de tour partagé par toutes les surfaces.

Deux outils existent : `propose_plan` (validé puis haché par le `Planner`) et `ask_user` (classe
`control`, hors gateway : aucune écriture externe). Un autre nom est refusé (`unknown_tool`).
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Annotated, Final, Literal, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from foreman.core.aliasing import Aliases
from foreman.core.catalog import TOOL_NAME_PATTERN
from foreman.core.clarification import (
    ASK_USER,
    AskUserArguments,
    ClarificationRefused,
    ClarificationRules,
    accepts,
    answer_text,
    card_of,
    round_of,
    with_status,
)
from foreman.core.events import (
    ERROR_MESSAGES,
    AnyEvent,
    ClarificationQuestion,
    ErrorData,
    EventData,
    MessageAuthor,
    MessageData,
    ToolCallData,
    TurnStatusData,
)
from foreman.core.gateway.errors import CallDenied, CallFailed
from foreman.core.gateway.port import Gateway, ReadCall
from foreman.core.gateway.redact import PRE_MASK_CHARS, mask_text
from foreman.core.planning import Draft, DraftStep, InvalidPlan, Planner, canonical_json
from foreman.core.ports import (
    ConversationMessage,
    EventLog,
    ModelReply,
    ProjectStore,
    Provider,
    ToolCall,
    ToolResult,
)
from foreman.core.pricing import ModelPrice
from foreman.core.turn_budget import MAX_TOOL_ROUNDS, TurnLimit, TurnMeter

logger = logging.getLogger(__name__)

FailureCode = Literal["internal_error", "unknown_tool", "invalid_plan", "budget_exceeded"]

PROPOSE_PLAN = "propose_plan"
DEFAULT_PROVIDER_TIMEOUT_S = 60.0
MAX_READS_PER_ROUND = 3
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_BYTES = 16 * 1024


@dataclass(frozen=True, slots=True)
class QuestionAnswer:
    """Réponse à une question : appliquée au début du tour qu'elle relance."""

    question_id: str
    value: str


@dataclass(frozen=True, slots=True)
class TurnRequest:
    user_id: UUID
    project_id: UUID
    message: str
    answer: QuestionAnswer | None = None
    user_name: str | None = None  # nom affiché de l'auteur du message


@dataclass(frozen=True, slots=True)
class QuestionOutcome:
    question_id: str
    status: Literal["answered", "deferred"]
    # Réponse : tour réservé, à jouer par la surface (`TurnService.run`). Report : `None`.
    turn: tuple[TurnRequest, UUID] | None = None


class TurnInProgress(Exception):
    """Un tour est déjà en cours pour ce projet."""


class QuestionRefused(Exception):
    """Réponse refusée ; `reason` est un code fermé, sans écho de la saisie."""

    def __init__(
        self, reason: Literal["not_found", "question_closed", "invalid_value", "turn_in_progress"]
    ) -> None:
        super().__init__(reason)
        self.reason = reason


class _PlanStepArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=200)]
    # Facultatifs : le planning (semaine 2, P7) les exige ; la carte de ce tour n'en dépend pas.
    tool: Annotated[str, Field(pattern=TOOL_NAME_PATTERN)] | None = None
    params: dict[str, JsonValue] | None = None


class ProposePlanArguments(BaseModel):
    """Arguments validés de l'outil `propose_plan` (le modèle n'est jamais cru sur parole)."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=200)]
    summary: Annotated[str, Field(max_length=500)]
    steps: Annotated[list[_PlanStepArgs], Field(min_length=1, max_length=20)]
    skills: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=10)
    # Facultatif ici ; le planning refuse un plan sans environnement (`invalid_plan`).
    environment: Annotated[str, Field(max_length=32)] | None = None
    stack: (
        dict[
            Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]*$")],
            Annotated[str, Field(max_length=100)],
        ]
        | None
    ) = Field(default=None, max_length=10)


def mask_for_model(text: str) -> str:
    """Masque les secrets avant l'envoi au modèle (ADR 0002). `mask_text` borne chaque appel à
    `PRE_MASK_CHARS` : le texte est traité par tranches, sans rien tronquer.

    shortcut: un secret à cheval sur deux tranches (plus de 2000 caractères d'un seul tenant)
    n'est pas reconnu ; à revoir si les messages peuvent porter des blocs de clé entiers.
    """
    return "".join(
        mask_text(text[i : i + PRE_MASK_CHARS]) for i in range(0, len(text), PRE_MASK_CHARS)
    )


def bounded_history(messages: Sequence[ConversationMessage]) -> list[ConversationMessage]:
    """Les derniers messages, au plus `MAX_HISTORY_MESSAGES` et `MAX_HISTORY_BYTES` (UTF-8).

    Le plus récent est toujours conservé : le modèle (et le replay) répondent à lui.
    """
    kept: list[ConversationMessage] = []
    size = 0
    for message in reversed(messages):
        size += len(message.text.encode("utf-8"))
        if kept and (len(kept) >= MAX_HISTORY_MESSAGES or size > MAX_HISTORY_BYTES):
            break
        kept.append(message)
    kept.reverse()
    return kept


# Liste d'autorisation (ADR 0002, couche 3) : seuls ces champs d'un diagnostic partent au modèle.
# Un champ ajouté plus tard au modèle de données reste côté serveur tant qu'il n'est pas ici.
MODEL_DIAGNOSTIC_FIELDS: Final = ("code", "expected", "observed", "probe", "extract")


def allowed_fields(values: Mapping[str, object]) -> dict[str, object]:
    return {name: values[name] for name in MODEL_DIAGNOSTIC_FIELDS if name in values}


def _aliased(value: object, aliases: Aliases) -> object:
    if isinstance(value, str):
        return aliases.apply(value)
    if isinstance(value, list):
        return [_aliased(item, aliases) for item in value]
    return value


def model_view(events: Sequence[AnyEvent]) -> tuple[list[ConversationMessage], Aliases]:
    """Ce que le modèle lit du flux : messages masqués et diagnostics typés, hôtes et valeurs
    internes remplacés par des alias stables ; les alias servent à `restore` (réponse)."""
    aliases = Aliases()
    history: list[ConversationMessage] = []
    for e in events:
        if e.type == "message":
            text = aliases.apply(mask_for_model(e.data.text))
            history.append(ConversationMessage(e.data.role, text))
        elif e.type == "execution_diagnostic":
            fields = allowed_fields(e.data.diagnostic.model_dump(exclude_none=True))
            result: dict[str, object] = {"tool": e.data.tool, "step": e.data.step}
            result |= {name: _aliased(value, aliases) for name, value in fields.items()}
            text = json.dumps({"tool_result": result}, ensure_ascii=False)
            history.append(ConversationMessage("user", text))
    return bounded_history(history), aliases


def model_history(events: Sequence[AnyEvent]) -> list[ConversationMessage]:
    return model_view(events)[0]


class TurnService:
    """Point d'entrée unique de la logique d'agent (web, CLI et webhooks l'appellent).

    Un seul tour à la fois par projet : `begin` réserve le projet de façon synchrone (aucun
    `await`), donc deux appels concurrents ne peuvent pas tous deux réussir.
    """

    def __init__(
        self,
        provider: Provider,
        events: EventLog,
        planner: Planner,
        projects: ProjectStore,
        gateway: Gateway,
        provider_timeout_s: float = DEFAULT_PROVIDER_TIMEOUT_S,
        prices: Mapping[str, ModelPrice] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._events = events
        self._planner = planner
        self._projects = projects
        self._gateway = gateway
        self._rules = ClarificationRules.from_catalog(planner.catalog)
        self._provider_timeout_s = provider_timeout_s
        self._prices = prices or {}
        self._clock = clock
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

    async def resolve_question(
        self,
        user_id: UUID,
        project_id: UUID,
        question_id: str,
        decision: Literal["answer", "defer"],
        value: str | None,
        user_name: str | None = None,
    ) -> QuestionOutcome:
        """Répond à une question ou la reporte. Lève `QuestionRefused`, sans rien écrire.

        Réponse : le message utilisateur du tour est canonique, produit ici à partir de la valeur
        choisie ; le tour est réservé et rendu à la surface, qui le joue. Une valeur hors options
        est refusée. Report : exécuté ici, sans tour de modèle.
        """
        question = self._find(await self._projects.get_open_questions(project_id), question_id)
        if question.status != "open":
            raise QuestionRefused("question_closed")
        if decision == "answer" and (value is None or not accepts(question, value)):
            raise QuestionRefused("invalid_value")
        try:
            turn_id = self.begin(project_id)
        except TurnInProgress:
            raise QuestionRefused("turn_in_progress") from None
        handed_over = False
        try:
            # Relu sous la réservation : deux réponses simultanées ne passent pas toutes deux.
            questions = await self._projects.get_open_questions(project_id)
            if self._find(questions, question_id).status != "open":
                raise QuestionRefused("question_closed")
            if decision == "defer" or value is None:
                updated = with_status(questions, question_id, "deferred")
                await self._projects.set_open_questions(project_id, updated)
                await self._emit(project_id, turn_id, card_of(round_of(question_id), updated))
                return QuestionOutcome(question_id, "deferred")
            request = TurnRequest(
                user_id=user_id,
                project_id=project_id,
                message=answer_text(question.field, value),
                answer=QuestionAnswer(question_id, value),
                user_name=user_name,
            )
            handed_over = True  # la surface joue le tour ; `run` libère la réservation
            return QuestionOutcome(question_id, "answered", (request, turn_id))
        finally:
            if not handed_over:
                self.release(project_id, turn_id)

    @staticmethod
    def _find(
        questions: Sequence[ClarificationQuestion], question_id: str
    ) -> ClarificationQuestion:
        for question in questions:
            if question.id == question_id:
                return question
        raise QuestionRefused("not_found")

    async def _emit(self, project_id: UUID, turn_id: UUID, data: EventData) -> None:
        await self._events.append(project_id, turn_id, data)

    async def _fail(self, project_id: UUID, turn_id: UUID, code: FailureCode) -> None:
        await self._emit(project_id, turn_id, ErrorData(code=code, message=ERROR_MESSAGES[code]))
        await self._emit(project_id, turn_id, TurnStatusData(status="failed"))

    async def _stop(
        self, project_id: UUID, turn_id: UUID, meter: TurnMeter, limit: TurnLimit
    ) -> None:
        """Arrêt propre sur dépassement : résumé, erreur `budget_exceeded`, tour en échec."""
        logger.warning(
            "turn_budget_exceeded project=%s turn=%s limit=%s", project_id, turn_id, limit
        )
        await self._emit(
            project_id, turn_id, MessageData(role="assistant", text=meter.summary(limit))
        )
        await self._fail(project_id, turn_id, "budget_exceeded")

    async def _history(self, project_id: UUID) -> tuple[list[ConversationMessage], Aliases]:
        return model_view(await self._events.read_after(project_id, 0))

    @staticmethod
    def _restored(reply: ModelReply, aliases: Aliases) -> ModelReply:
        """Remet hôtes et valeurs d'origine dans la réponse (texte et arguments d'outils)."""
        text = str(aliases.restore(reply.text))
        calls = tuple(
            ToolCall(c.name, cast(Mapping[str, object], aliases.restore(c.arguments)), c.id)
            for c in reply.tool_calls
        )
        return replace(reply, text=text, tool_calls=calls)

    async def _run(self, request: TurnRequest, turn_id: UUID) -> None:
        project_id = request.project_id
        author = (
            MessageAuthor(id=request.user_id, name=request.user_name) if request.user_name else None
        )
        await self._emit(
            project_id, turn_id, MessageData(role="user", text=request.message, author=author)
        )
        await self._emit(project_id, turn_id, TurnStatusData(status="running"))
        if request.answer is not None:
            questions = await self._projects.get_open_questions(project_id)
            answer = request.answer
            updated = with_status(questions, answer.question_id, "answered", answer.value)
            await self._projects.set_open_questions(project_id, updated)
            await self._emit(project_id, turn_id, card_of(round_of(answer.question_id), updated))
        limits = self._planner.catalog.policy.budgets.per_turn
        meter = TurnMeter(limits, self._prices, self._clock)
        history: list[ConversationMessage] | None = None
        aliases = Aliases()
        while True:
            if (limit := meter.admit()) is not None:
                await self._stop(project_id, turn_id, meter, limit)
                return
            remaining = meter.remaining()
            try:
                # Délai explicite : sinon un fournisseur muet bloque le projet en 409 pour toujours.
                async with asyncio.timeout(min(self._provider_timeout_s, remaining)):
                    if history is None:
                        history, aliases = await self._history(project_id)
                    raw = await self._provider.complete(history)
                    raw = replace(
                        raw,
                        tool_calls=tuple(
                            c if c.id else replace(c, id=f"call_{meter.tool_rounds}_{i}")
                            for i, c in enumerate(raw.tool_calls)
                        ),
                    )
                    reply = self._restored(raw, aliases)
                meter.record(reply.usage)
            except TimeoutError:
                if remaining <= self._provider_timeout_s:
                    await self._stop(project_id, turn_id, meter, "duration")
                    return
                logger.exception("provider_failed project=%s turn=%s", project_id, turn_id)
                await self._fail(project_id, turn_id, "internal_error")
                return
            except Exception:
                logger.exception("provider_failed project=%s turn=%s", project_id, turn_id)
                await self._fail(project_id, turn_id, "internal_error")
                return
            # Coût visible dans les logs serveur : nombres et identifiants seulement, aucun contenu.
            logger.info(
                "turn_cost project=%s turn=%s model=%s tokens=%d cost_eur=%.6f",
                project_id,
                turn_id,
                reply.usage.model if reply.usage else "replay",
                meter.tokens,
                meter.cost,
            )
            if (limit := meter.over()) is not None:
                # Le coût est engagé mais rien de ce que la réponse demande n'est exécuté.
                await self._stop(project_id, turn_id, meter, limit)
                return
            if not self._only_reads(reply.tool_calls):
                break
            if meter.tool_rounds >= MAX_TOOL_ROUNDS:
                await self._stop(project_id, turn_id, meter, "tool_rounds")
                return
            meter.tool_rounds += 1
            try:
                # Les lectures partagent l'échéance du tour (le verrou du projet est tenu).
                async with asyncio.timeout(meter.remaining()):
                    results = await self._read(
                        request.user_id, project_id, turn_id, reply.tool_calls, aliases
                    )
            except TimeoutError:
                await self._stop(project_id, turn_id, meter, "duration")
                return
            # En mémoire seulement : le journal d'événements ne voit ni appels ni résultats.
            history.append(
                ConversationMessage(
                    "assistant",
                    aliases.apply(mask_for_model(raw.text)),
                    tool_calls=raw.tool_calls,
                )
            )
            payload = [
                {"call_id": r.call_id, "is_error": r.is_error, "text": r.text} for r in results
            ]
            history.append(
                ConversationMessage(
                    "user", canonical_json(payload).decode("utf-8"), tool_results=results
                )
            )
        await self._emit(project_id, turn_id, MessageData(role="assistant", text=reply.text))
        for call in reply.tool_calls:
            failure = await self._apply(request.user_id, project_id, turn_id, call)
            if failure is not None:
                await self._fail(project_id, turn_id, failure)
                return
        await self._emit(project_id, turn_id, TurnStatusData(status="completed"))

    def _only_reads(self, calls: Sequence[ToolCall]) -> bool:
        tools, connectors = self._planner.catalog.tools, self._planner.catalog.connectors
        return bool(calls) and all(
            (t := tools.get(c.name)) is not None
            and t.tool_class == "read"
            and (k := connectors.get(t.connector)) is not None
            and k.availability == "available"  # « bientôt » : caché du modèle, donc refusé
            for c in calls
        )

    async def _read(
        self,
        user_id: UUID,
        project_id: UUID,
        turn_id: UUID,
        calls: Sequence[ToolCall],
        aliases: Aliases,
    ) -> tuple[ToolResult, ...]:
        """Lectures via la gateway (seule voie) ; un refus ou un échec devient un résultat d'erreur
        à code fermé, le tour continue. Le contenu lu est non fiable : masqué puis aliasé."""
        results: list[ToolResult] = []
        for i, call in enumerate(calls):
            error: str | None = None
            output: object = None
            if i >= MAX_READS_PER_ROUND:
                error = "limit_reached"
            else:
                try:
                    params = cast(Mapping[str, JsonValue], call.arguments)
                    output = await self._gateway.read(
                        ReadCall(project_id, user_id, call.name, params)
                    )
                except (CallDenied, CallFailed) as refused:
                    error = refused.code
                    logger.warning(
                        "read_refused project=%s turn=%s code=%s", project_id, turn_id, error
                    )
            await self._emit(
                project_id,
                turn_id,
                ToolCallData(tool=call.name, outcome="error" if error else "ok"),
            )
            raw = canonical_json({"error": error} if error else output).decode("utf-8")
            results.append(
                ToolResult(call.id, aliases.apply(mask_for_model(raw)), error is not None)
            )
        return tuple(results)

    async def _apply(
        self, user_id: UUID, project_id: UUID, turn_id: UUID, call: ToolCall
    ) -> FailureCode | None:
        """Code d'erreur ou `None`. Seuls `propose_plan` et `ask_user` existent."""
        if call.name == ASK_USER:
            return await self._ask_user(project_id, turn_id, call)
        if call.name != PROPOSE_PLAN:
            logger.warning("unknown_tool project=%s turn=%s", project_id, turn_id)
            return "unknown_tool"
        try:
            # Tant qu'une question requise est ouverte, on ne planifie pas.
            if self._rules.blocking(await self._projects.get_open_questions(project_id)):
                raise InvalidPlan
            arguments = ProposePlanArguments.model_validate(call.arguments)
            draft = Draft(
                title=arguments.title,
                summary=arguments.summary,
                steps=[DraftStep(s.title, s.tool, s.params or {}) for s in arguments.steps],
                environment=arguments.environment,
                stack=arguments.stack,
                skills=arguments.skills,
            )
            # Valide, hache et persiste : un plan refusé n'écrit rien et n'émet aucune carte.
            record, content = await self._planner.propose(project_id, draft, user_id)
        except (ValidationError, InvalidPlan):
            logger.warning("invalid_plan project=%s turn=%s", project_id, turn_id)
            return "invalid_plan"
        await self._emit(project_id, turn_id, self._planner.card(record, content))
        return None

    async def _ask_user(
        self, project_id: UUID, turn_id: UUID, call: ToolCall
    ) -> FailureCode | None:
        """Classe `control` : aucune écriture externe. Questions persistées avant la carte."""
        try:
            arguments = AskUserArguments.model_validate(call.arguments)
            existing = await self._projects.get_open_questions(project_id)
            round_, new = self._rules.ask(arguments, existing)
        except (ValidationError, ClarificationRefused):
            logger.warning("invalid_ask_user project=%s turn=%s", project_id, turn_id)
            return "invalid_plan"
        await self._projects.set_open_questions(project_id, [*existing, *new])
        await self._emit(project_id, turn_id, card_of(round_, new))
        return None
