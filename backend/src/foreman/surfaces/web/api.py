"""Routes de l'API (contrat figé v1)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import JsonValue

from foreman.bootstrap.configure import App
from foreman.core.events import AnyEvent
from foreman.core.execution.cards import execution_card
from foreman.core.identity import Principal
from foreman.core.ports import CapacityExceeded
from foreman.core.projects import Project
from foreman.core.store import ApprovalRefused, AwaitingAdmin
from foreman.core.turn import QuestionRefused, TurnInProgress, TurnRequest
from foreman.surfaces.web.auth import make_current_principal
from foreman.surfaces.web.errors import ApiError
from foreman.surfaces.web.schemas import (
    AdminApprovalRequest,
    ApprovalAccepted,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
    CreateProjectRequest,
    ErrorResponse,
    ExecutionStepView,
    ExecutionView,
    Me,
    MessageAccepted,
    MessageRequest,
    PlanView,
    QuestionAccepted,
    QuestionAnswerRequest,
)
from foreman.surfaces.web.tasks import TaskRegistry

_ERRORS: dict[int | str, dict[str, Any]] = {
    # Descriptions explicites : la bibliothèque standard les libelle différemment selon la version
    # de Python, ce qui ferait varier openapi.json entre le poste et la CI.
    401: {"model": ErrorResponse, "description": "Non authentifié (`unauthenticated`)"},
    403: {"model": ErrorResponse, "description": "Rôle insuffisant (`forbidden`)"},
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


_REFUSALS: dict[str, int] = {"not_found": 404, "forbidden": 403}  # le reste : 409


def _refused(refusal: ApprovalRefused) -> ApiError:
    return ApiError(_REFUSALS.get(refusal.reason, 409), refusal.reason)


def create_router(app: App, tasks: TaskRegistry) -> APIRouter:
    current_principal = make_current_principal(app)
    # Toute route de l'API exige une identité (401 en `proxy_header`) ; en `none`, c'est `dev`.
    router = APIRouter(prefix="/api", dependencies=[Depends(current_principal)])
    Caller = Annotated[Principal, Depends(current_principal)]

    @router.post("/projects", status_code=201, response_model=Project, responses=_ERRORS)
    async def create_project(body: CreateProjectRequest | None = None) -> Project:
        """Crée un projet. Le corps est facultatif (`title` vaut alors une chaîne vide)."""
        try:
            return await app.projects.create(body.title if body else "")
        except CapacityExceeded:
            raise ApiError(503, "capacity_exceeded") from None

    @router.get("/projects", response_model=list[Project], responses=_ERRORS)
    async def list_projects() -> list[Project]:
        """Projets connus du serveur, du plus récent au plus ancien."""
        return await app.projects.list()

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
    async def post_message(
        project_id: UUID, body: MessageRequest, caller: Caller
    ) -> MessageAccepted:
        """Un seul tour à la fois par projet : un second message pendant un tour renvoie 409."""
        if await app.projects.get(project_id) is None:
            raise ApiError(404, "not_found")
        try:
            turn_id = app.turns.begin(project_id)
        except TurnInProgress:
            raise ApiError(409, "turn_in_progress") from None
        request = TurnRequest(user_id=caller.user_id, project_id=project_id, message=body.text)
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

    @router.post(
        "/projects/{project_id}/plans/{plan_id}/approvals",
        status_code=201,
        response_model=ApprovalAccepted,
        responses={
            **_ERRORS,
            202: {
                "model": ApprovalPending,
                "description": (
                    "Validé par le développeur, en attente d'un administrateur "
                    "(`approval_required`) : aucune exécution n'est créée"
                ),
            },
            200: {
                "model": ApprovalAccepted,
                "description": (
                    "Rejeu idempotent : le plan est déjà approuvé avec ce hash ; "
                    "mêmes `approval_id` et `execution_id` que la création"
                ),
            },
            404: {
                "model": ErrorResponse,
                "description": "Introuvable, y compris un plan d'un autre projet",
            },
            409: {
                "model": ErrorResponse,
                "description": (
                    "`plan_hash_mismatch` (hash différent de celui du plan), "
                    "`plan_not_approvable` (expiré, invalidé ou exécuté), "
                    "`execution_in_progress`, `policy_denied` (étape interdite au rôle)"
                ),
            },
        },
    )
    async def approve_plan(
        project_id: UUID, plan_id: UUID, body: ApprovalRequest, response: Response, caller: Caller
    ) -> ApprovalAccepted | JSONResponse:
        """Le développeur valide son plan : l'approbation porte sur le hash affiché.

        Si l'environnement exige un administrateur, la validation est écrite sans exécution (202).
        """
        if app.approvals is None or app.engine is None:
            raise ApiError(501, "not_implemented")
        result = await app.approvals.approve(project_id, plan_id, body.plan_hash, caller)
        if isinstance(result, ApprovalRefused):
            raise _refused(result)
        if isinstance(result, AwaitingAdmin):
            pending = ApprovalPending(
                approval_id=result.approval_id,
                status="approval_required",
                missing=["admin_approved"],
            )
            return JSONResponse(status_code=202, content=pending.model_dump(mode="json"))
        if result.created:
            # Les cartes sont déjà émises (plan puis exécution) : le moteur peut partir.
            tasks.spawn(app.engine.run(project_id, result.execution_id))
        else:
            response.status_code = 200  # rejeu idempotent : mêmes identifiants
        return ApprovalAccepted(approval_id=result.approval_id, execution_id=result.execution_id)

    @router.post(
        "/projects/{project_id}/plans/{plan_id}/admin-approvals",
        status_code=201,
        response_model=ApprovalAccepted,
        responses={
            **_ERRORS,
            200: {
                "model": ApprovalAccepted | ApprovalRejected,
                "description": (
                    "Rejeu idempotent d'une approbation (`ApprovalAccepted`, mêmes identifiants), "
                    "ou refus (`decision: rejected`, `ApprovalRejected`) : le plan est invalidé"
                ),
            },
            409: {
                "model": ErrorResponse,
                "description": (
                    "`plan_hash_mismatch`, `plan_not_approvable` (expiré, invalidé, pas encore "
                    "validé par le développeur) ou `execution_in_progress`"
                ),
            },
        },
    )
    async def admin_approve_plan(
        project_id: UUID,
        plan_id: UUID,
        body: AdminApprovalRequest,
        response: Response,
        caller: Caller,
    ) -> ApprovalAccepted | JSONResponse:
        """Un administrateur approuve (crée l'exécution et la démarre) ou refuse un plan.

        Seuls les rôles de `approvers.admin` le peuvent (sinon 403, rien n'est écrit).
        """
        if app.approvals is None or app.engine is None:
            raise ApiError(501, "not_implemented")
        if body.decision == "rejected":
            rejected = await app.approvals.reject_admin(project_id, plan_id, body.plan_hash, caller)
            if isinstance(rejected, ApprovalRefused):
                raise _refused(rejected)
            refusal = ApprovalRejected(approval_id=rejected.approval_id, status="rejected")
            return JSONResponse(status_code=200, content=refusal.model_dump(mode="json"))
        approved = await app.approvals.approve_admin(project_id, plan_id, body.plan_hash, caller)
        if isinstance(approved, ApprovalRefused):
            raise _refused(approved)
        if approved.created:
            tasks.spawn(app.engine.run(project_id, approved.execution_id))
        else:
            response.status_code = 200  # rejeu idempotent
        return ApprovalAccepted(
            approval_id=approved.approval_id, execution_id=approved.execution_id
        )

    @router.get("/me", response_model=Me, responses=_ERRORS)
    async def get_me(caller: Caller) -> Me:
        """Identité de l'appelant, lue côté serveur (rôle : `FOREMAN_DEV_MEMBERS`)."""
        return Me(user_id=str(caller.user_id), name=caller.name, role=caller.role)

    @router.post(
        "/projects/{project_id}/questions/{question_id}",
        status_code=202,
        response_model=QuestionAccepted,
        responses={
            **_ERRORS,
            200: {
                "model": QuestionAccepted,
                "description": "Question reportée (`decision: defer`)",
            },
            404: {
                "model": ErrorResponse,
                "description": "Introuvable, y compris une question d'un autre projet",
            },
            409: {
                "model": ErrorResponse,
                "description": "`turn_in_progress` ou `question_closed` (déjà répondue)",
            },
        },
    )
    async def answer_question(
        project_id: UUID,
        question_id: str,
        body: QuestionAnswerRequest,
        response: Response,
        caller: Caller,
    ) -> QuestionAccepted:
        """Répond à une question de clarification (202, relance un tour) ou la reporte (200).

        La réponse doit être l'une des options de la question ; le message du tour est produit
        par le serveur à partir de ce choix. Un refus ne lance aucun tour ni ne cite la saisie.
        """
        if await app.projects.get(project_id) is None:
            raise ApiError(404, "not_found")
        try:
            outcome = await app.turns.resolve_question(
                caller.user_id, project_id, question_id, body.decision, body.value
            )
        except QuestionRefused as refused:
            if refused.reason == "not_found":
                raise ApiError(404, "not_found") from None
            if refused.reason == "invalid_value":
                raise ApiError(422, "invalid_request") from None
            raise ApiError(409, refused.reason) from None
        if outcome.turn is None:
            response.status_code = 200  # report : rien à rejouer
        else:
            request, turn_id = outcome.turn
            try:
                tasks.spawn(app.turns.run(request, turn_id))
            except BaseException:
                app.turns.release(project_id, turn_id)
                raise
        return QuestionAccepted(question_id=outcome.question_id, status=outcome.status)

    @router.get(
        "/projects/{project_id}/plans/{plan_id}", response_model=PlanView, responses=_ERRORS
    )
    async def get_plan(project_id: UUID, plan_id: UUID) -> PlanView:
        # Un plan d'un autre projet est introuvable (404), jamais interdit.
        record = await app.stores.plans.get(project_id, plan_id)
        if record is None:
            raise ApiError(404, "not_found")
        return PlanView(
            id=record.id,
            version=record.version,
            status=record.status,
            content_hash=record.content_hash,
            content=cast(dict[str, JsonValue], dict(record.content)),
            created_at=record.created_at,
            expires_at=record.expires_at,
        )

    @router.get(
        "/projects/{project_id}/executions/{execution_id}",
        response_model=ExecutionView,
        responses=_ERRORS,
    )
    async def get_execution(project_id: UUID, execution_id: UUID) -> ExecutionView:
        """Vue reconstruite de l'état persisté (`elapsed_s` : connu de la carte vive seulement)."""
        if app.engine is None or app.catalog is None:
            raise ApiError(501, "not_implemented")
        execution = await app.stores.executions.get(project_id, execution_id)
        card = await execution_card(app.stores, app.catalog, project_id, execution_id)
        if execution is None or card is None:
            raise ApiError(404, "not_found")  # aussi pour l'exécution d'un autre projet
        return ExecutionView(
            id=card.execution_id,
            plan_id=execution.plan_id,
            plan_card_id=card.plan_card_id,
            state=card.state,
            autonomy_level=card.autonomy_level,
            budget=card.budget,
            steps=[
                ExecutionStepView(step=s.step, title=s.title, tool=s.tool or "", status=s.status)
                for s in card.steps
            ],
            resources=card.resources,
            result=card.result,
        )

    return router
