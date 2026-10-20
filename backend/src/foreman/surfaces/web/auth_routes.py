"""Routes d'authentification (mode `session`) : connexion, déconnexion, première invitation.

Toutes les erreurs sont opaques : e-mail inconnu, mot de passe faux et compte désactivé donnent la
même réponse. Les échecs (login et acceptation) sont limités par adresse et par e-mail.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from foreman.bootstrap.configure import App, AuthMode
from foreman.core.accounts import AccountError
from foreman.core.auth import AuthStore, csrf_for, new_token, token_hash
from foreman.core.identity import Principal
from foreman.surfaces.web.auth import (
    COOKIE,
    make_current_principal,
    same_origin,
    set_session_cookie,
)
from foreman.surfaces.web.errors import ApiError
from foreman.surfaces.web.ratelimit import FailureLimiter
from foreman.surfaces.web.schemas import AcceptInviteRequest, ErrorResponse, LoginRequest

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Identifiants invalides (`unauthenticated`)"},
    403: {"model": ErrorResponse, "description": "Origine ou jeton CSRF refusé (`forbidden`)"},
    404: {"model": ErrorResponse, "description": "Mode `session` inactif"},
    422: {"model": ErrorResponse, "description": "Requête ou invitation invalide"},
    429: {"model": ErrorResponse, "description": "Trop d'échecs (`too_many_requests`)"},
}


def create_auth_router(app: App) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    limiter = FailureLimiter()
    current_principal = make_current_principal(app)

    def gate(request: Request, email: str) -> tuple[AuthStore, tuple[str, str], str]:
        """Mode actif, `Origin` de même hôte, limite non atteinte. Renvoie (store, clés, e-mail)."""
        if app.auth_mode is not AuthMode.SESSION or app.auth is None or app.accounts is None:
            raise ApiError(404, "not_found")
        if not same_origin(request):
            raise ApiError(403, "forbidden")
        email = email.strip().lower()
        keys = (f"ip:{request.client.host if request.client else '?'}", f"email:{email}")
        if limiter.blocked(*keys):
            raise ApiError(429, "too_many_requests")
        return app.auth, keys, email

    @router.post("/login", status_code=204, responses=_ERRORS)
    async def login(body: LoginRequest, request: Request) -> Response:
        auth, keys, email = gate(request, body.email)
        known = await auth.credentials(email)
        usable = known is not None and not known.disabled
        verified = await app.hasher.verify(
            known.password_hash if known and usable else None, body.password
        )
        user_id = known.user_id if known else None
        await auth.record_login(user_id, verified)
        if not verified or known is None:
            limiter.fail(*keys)
            raise ApiError(401, "unauthenticated")
        limiter.reset(keys[1])
        token, response = new_token(), Response(status_code=204)
        await auth.open_session(
            token_hash(token), token_hash(csrf_for(token)), known.user_id, datetime.now(UTC)
        )
        set_session_cookie(app, response, token)
        return response

    @router.post("/accept-invite", status_code=204, responses=_ERRORS)
    async def accept_invite(body: AcceptInviteRequest, request: Request) -> Response:
        _, keys, email = gate(request, body.email)
        assert app.accounts is not None  # noqa: S101 - garanti par gate()
        password_hash = await app.hasher.hash(body.password)
        try:
            await app.accounts.accept_invitation(
                token_hash(body.token), email, body.name, password_hash, datetime.now(UTC)
            )
        except AccountError:  # invitation inconnue, expirée, utilisée, e-mail différent, doublon
            limiter.fail(*keys)
            raise ApiError(422, "invalid_request") from None
        return Response(status_code=204)

    @router.post("/logout", status_code=204, responses=_ERRORS)
    async def logout(
        request: Request, response: Response, _: Annotated[Principal, Depends(current_principal)]
    ) -> None:
        assert app.auth is not None  # noqa: S101 - la dépendance a validé la session
        await app.auth.close_session(token_hash(request.state.session_token))
        # Même objet que celui de la dépendance : la suppression suit son renouvellement du cookie.
        response.delete_cookie(COOKIE, path="/")

    return router
