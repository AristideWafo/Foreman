"""Identité de l'appelant : dépendance FastAPI `current_principal`.

`none` (défaut, poste et CI) : utilisateur `dev` unique, l'en-tête est IGNORÉ (un client ne peut
pas se faire passer pour un autre). `proxy_header` : Traefik pose `X-Forwarded-User` après
basicAuth (et écrase celui du client) ; sans en-tête ou pour un nom inconnu : 401 opaque, sans
écho du nom. Le rôle vient toujours de `MemberStore` (par équipe), jamais de la requête.

`session` : cookie de session (condensat en base). Session absente, expirée ou compte désactivé :
401 opaque. Toute méthode non sûre exige en plus `X-Foreman-CSRF` (jeton rendu par `GET /me`) et
un `Origin` de même hôte : sinon 403. Le rôle est relu en base à chaque requête.
"""

import hmac
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, Request, Response

from foreman.bootstrap.configure import App, AuthMode
from foreman.core.auth import SESSION_TTL, csrf_for, token_hash
from foreman.core.identity import Principal, member_id
from foreman.core.projects import Project
from foreman.core.store import DEV_TEAM_ID, DEV_USER_ID, DEV_USER_NAME
from foreman.surfaces.web.errors import ApiError

FORWARDED_USER = "X-Forwarded-User"
COOKIE = "foreman_session"
CSRF_HEADER = "X-Foreman-CSRF"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_NAME_LENGTH = 100

DEV_PRINCIPAL = Principal(user_id=DEV_USER_ID, name=DEV_USER_NAME, role="developer")


def same_origin(request: Request) -> bool:
    """`Origin` présent et de même hôte que la requête (le schéma peut être terminé en amont)."""
    netloc = urlsplit(request.headers.get("origin", "")).netloc
    return bool(netloc) and netloc == request.headers.get("host")


def set_session_cookie(app: App, response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=app.cookie_secure,
        samesite="lax",
        path="/",
    )


async def _session_principal(app: App, request: Request, response: Response) -> Principal:
    token = request.cookies.get(COOKIE, "")
    if app.auth is None or not token or len(token) > 100:
        raise ApiError(401, "unauthenticated")
    info = await app.auth.session(token_hash(token), datetime.now(UTC))
    if info is None:
        raise ApiError(401, "unauthenticated")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not same_origin(request) or not hmac.compare_digest(token_hash(sent), info.csrf_hash):
            raise ApiError(403, "forbidden")
    request.state.session_token = token
    request.state.csrf_token = csrf_for(token)
    set_session_cookie(app, response, token)  # session glissante : le cookie suit le serveur
    return Principal(user_id=info.user_id, name=info.name, role=info.role)


def make_current_principal(app: App) -> Callable[[Request, Response], Awaitable[Principal]]:
    async def current_principal(request: Request, response: Response) -> Principal:
        if app.auth_mode is AuthMode.NONE:
            return DEV_PRINCIPAL
        if app.auth_mode is AuthMode.SESSION:
            return await _session_principal(app, request, response)
        name = request.headers.get(FORWARDED_USER, "").strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ApiError(401, "unauthenticated")
        user_id = member_id(name)
        role = await app.members.role_in(user_id, DEV_TEAM_ID)
        if role is None:
            raise ApiError(401, "unauthenticated")
        return Principal(user_id=user_id, name=name, role=role)

    return current_principal


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """Projet accessible et appelant dont `role` est son rôle DANS L'ÉQUIPE de ce projet."""

    project: Project
    principal: Principal


async def resolve_access(app: App, caller: Principal, project_id: UUID) -> ProjectAccess | None:
    """`None` si le projet n'existe pas OU si l'appelant n'y a pas accès (indiscernables)."""
    project = await app.projects.get(project_id)
    if project is None:
        return None
    role = await app.members.role_in(caller.user_id, project.team_id)
    if role is None:
        # Équipe personnelle : l'approbateur admin désigné doit pouvoir voir le plan à valider.
        designated = await app.members.designated_admins(project.team_id)
        if designated and caller.user_id in designated:
            role = "team_admin"
    if role is None:
        return None
    return ProjectAccess(project, caller.model_copy(update={"role": role}))


def make_project_access(
    app: App, current_principal: Callable[..., Awaitable[Principal]]
) -> Callable[..., Awaitable[ProjectAccess]]:
    """Seule porte d'accès aux routes `/projects/{project_id}/...` : accès refusé = 404 opaque."""

    async def project_access(
        project_id: UUID, caller: Annotated[Principal, Depends(current_principal)]
    ) -> ProjectAccess:
        access = await resolve_access(app, caller, project_id)
        if access is None:
            raise ApiError(404, "not_found")
        return access

    return project_access
