"""API d'administration : équipes, membres, rôles, invitations (mode `session` seulement).

L'autorisation se décide côté serveur, depuis la base (`AccountStore.admin_scope`), jamais depuis
le corps. org_admin : tout. team_admin : SES équipes partagées. Les autres : 403 sur tout `/admin`.
Le store reste l'autorité (anti-élévation, derniers admins) ; la route écarte tôt ce qui sort du
périmètre. Chaque mutation est auditée par le store, dans sa transaction.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from foreman.bootstrap.configure import App, AuthMode, invitation_link
from foreman.core.accounts import (
    AccountError,
    AccountStore,
    AdminScope,
    Conflict,
    ElevationDenied,
    InvalidInvitation,
    LastAdmin,
    LastTeamAdmin,
    NotFound,
    PersonalTeam,
)
from foreman.core.auth import INVITATION_TTL, new_token, token_hash
from foreman.core.identity import Principal
from foreman.core.ports import CapacityExceeded
from foreman.surfaces.web.admin_integrations import add_integration_routes
from foreman.surfaces.web.auth import make_current_principal
from foreman.surfaces.web.errors import ApiError
from foreman.surfaces.web.schemas import (
    CreateInvitationRequest,
    CreateTeamRequest,
    ErrorResponse,
    InvitationCreated,
    InvitationView,
    MembershipView,
    MoveProjectRequest,
    SetRoleRequest,
    TeamView,
    UserView,
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Non authentifié (`unauthenticated`)"},
    403: {"model": ErrorResponse, "description": "Droits insuffisants ou CSRF (`forbidden`)"},
    404: {"model": ErrorResponse, "description": "Introuvable ou mode `session` inactif"},
    409: {
        "model": ErrorResponse,
        "description": "`last_admin`, `last_team_admin`, `invalid_invitation` ou `conflict`",
    },
    422: {"model": ErrorResponse, "description": "Requête invalide"},
    503: {"model": ErrorResponse, "description": "Capacité atteinte"},
}
MAX_LIMIT = 1_000  # = plafond de comptes ; au-delà, rien de plus à lister
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


@contextmanager
def refusals() -> Iterator[None]:
    """Refus de domaine -> erreur opaque (jamais le message de l'exception)."""
    try:
        yield
    except LastAdmin:
        raise ApiError(409, "last_admin") from None
    except LastTeamAdmin:
        raise ApiError(409, "last_team_admin") from None
    except InvalidInvitation:
        raise ApiError(409, "invalid_invitation") from None
    except (Conflict, PersonalTeam):
        raise ApiError(409, "conflict") from None
    except ElevationDenied:
        raise ApiError(403, "forbidden") from None
    except NotFound:
        raise ApiError(404, "not_found") from None
    except CapacityExceeded:
        raise ApiError(503, "capacity_exceeded") from None
    except AccountError:
        raise ApiError(422, "invalid_request") from None


def create_admin_router(app: App) -> APIRouter:
    current_principal = make_current_principal(app)

    def accounts() -> AccountStore:
        if app.auth_mode is not AuthMode.SESSION or app.accounts is None:
            raise ApiError(404, "not_found")
        return app.accounts

    async def admin_scope(
        caller: Annotated[Principal, Depends(current_principal)],
    ) -> AdminScope:
        scope = await accounts().admin_scope(caller.user_id)
        if not scope.is_admin:
            raise ApiError(403, "forbidden")
        return scope

    router = APIRouter(prefix="/api/admin", tags=["admin"], responses=_ERRORS)
    Caller = Annotated[Principal, Depends(current_principal)]
    Scope = Annotated[AdminScope, Depends(admin_scope)]

    def team_scope(scope: AdminScope, team_id: UUID) -> None:
        if not scope.covers(team_id):
            raise ApiError(403, "forbidden")

    def org_only(scope: AdminScope) -> None:
        if not scope.org:
            raise ApiError(403, "forbidden")

    def visible(scope: AdminScope) -> frozenset[UUID] | None:
        return None if scope.org else scope.teams

    @router.get("/teams", response_model=list[TeamView])
    async def list_teams(scope: Scope, limit: Limit = 200) -> list[TeamView]:
        with refusals():
            teams = await accounts().list_teams(visible(scope), limit)
        return [TeamView(id=x.id, name=x.name) for x in teams]

    @router.post("/teams", status_code=201, response_model=TeamView)
    async def create_team(body: CreateTeamRequest, caller: Caller, scope: Scope) -> TeamView:
        org_only(scope)
        with refusals():
            team = await accounts().create_team(
                body.name.strip(), body.first_admin_id, caller.user_id
            )
        return TeamView(id=team.id, name=team.name)

    @router.get("/users", response_model=list[UserView])
    async def list_users(scope: Scope, limit: Limit = 200) -> list[UserView]:
        with refusals():
            users = await accounts().list_users(visible(scope), limit)
        return [
            UserView(
                id=u.id,
                email=u.email,
                name=u.name,
                disabled=u.disabled,
                memberships=[
                    MembershipView(team_id=m.team_id, team_name=m.team_name, role=m.role)
                    for m in u.memberships
                ],
            )
            for u in users
        ]

    @router.put("/teams/{team_id}/members/{user_id}", status_code=204)
    async def set_member_role(
        team_id: UUID, user_id: UUID, body: SetRoleRequest, caller: Caller, scope: Scope
    ) -> Response:
        """Rattache `user_id` à l'équipe (rôle donné) ou change son rôle."""
        team_scope(scope, team_id)
        store = accounts()
        with refusals():
            try:
                await store.change_role(team_id, user_id, body.role, caller.user_id)
            except NotFound:  # pas encore membre : rattachement (échoue en NotFound si inconnu)
                await store.add_member(team_id, user_id, body.role, caller.user_id)
        return Response(status_code=204)

    @router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
    async def remove_member(team_id: UUID, user_id: UUID, caller: Caller, scope: Scope) -> Response:
        team_scope(scope, team_id)
        with refusals():
            await accounts().remove_member(team_id, user_id, caller.user_id)
        return Response(status_code=204)

    @router.post("/users/{user_id}/disable", status_code=204)
    async def disable_user(user_id: UUID, caller: Caller, scope: Scope) -> Response:
        """Désactive le compte et supprime ses sessions (org_admin : l'effet est global)."""
        org_only(scope)
        with refusals():
            await accounts().disable_account(user_id, caller.user_id)
        return Response(status_code=204)

    @router.put("/projects/{project_id}/team", status_code=204)
    async def move_project(
        project_id: UUID, body: MoveProjectRequest, caller: Caller, scope: Scope
    ) -> Response:
        org_only(scope)
        with refusals():
            await accounts().move_project(project_id, body.team_id, caller.user_id)
        return Response(status_code=204)

    @router.post("/invitations", status_code=201, response_model=InvitationCreated)
    async def create_invitation(
        body: CreateInvitationRequest, caller: Caller, scope: Scope
    ) -> InvitationCreated:
        """Le lien (jeton compris) n'est rendu qu'ici : seul son condensat est stocké."""
        if body.team_id is None:
            org_only(scope)
        else:
            team_scope(scope, body.team_id)
        if body.role == "org_admin" and body.team_id is not None:
            raise ApiError(422, "invalid_request")
        token = new_token()
        with refusals():
            inv = await accounts().create_invitation(
                token_hash(token),
                body.email.strip(),
                body.team_id,
                body.role,
                caller.user_id,
                datetime.now(UTC) + INVITATION_TTL,
            )
        return InvitationCreated(
            id=inv.id,
            email=inv.email,
            team_id=inv.team_id,
            role=inv.role,
            expires_at=inv.expires_at,
            link=invitation_link(token),
        )

    @router.get("/invitations", response_model=list[InvitationView])
    async def list_invitations(scope: Scope, limit: Limit = 200) -> list[InvitationView]:
        with refusals():
            found = await accounts().list_invitations(visible(scope), limit)
        return [
            InvitationView(
                id=i.id, email=i.email, team_id=i.team_id, role=i.role, expires_at=i.expires_at
            )
            for i in found
        ]

    @router.delete("/invitations/{invitation_id}", status_code=204)
    async def revoke_invitation(invitation_id: UUID, caller: Caller, scope: Scope) -> Response:
        with refusals():
            await accounts().revoke_invitation(invitation_id, caller.user_id)
        return Response(status_code=204)

    add_integration_routes(
        router,
        app,
        current_principal=current_principal,
        admin_scope=admin_scope,
        org_only=org_only,
        refusals=refusals,
    )
    return router
