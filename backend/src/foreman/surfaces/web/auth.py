"""Identité de l'appelant : dépendance FastAPI `current_principal`.

`none` (défaut, poste et CI) : utilisateur `dev` unique, l'en-tête est IGNORÉ (un client ne peut
pas se faire passer pour un autre). `proxy_header` : Traefik pose `X-Forwarded-User` après
basicAuth (et écrase celui du client) ; sans en-tête ou pour un nom inconnu : 401 opaque, sans
écho du nom. Le rôle vient toujours de `MemberStore`, jamais de la requête.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request

from foreman.bootstrap.configure import App, AuthMode
from foreman.core.identity import Principal, member_id
from foreman.core.store import DEV_USER_ID, DEV_USER_NAME
from foreman.surfaces.web.errors import ApiError

FORWARDED_USER = "X-Forwarded-User"
MAX_NAME_LENGTH = 100

DEV_PRINCIPAL = Principal(user_id=DEV_USER_ID, name=DEV_USER_NAME, role="developer")


def make_current_principal(app: App) -> Callable[[Request], Awaitable[Principal]]:
    async def current_principal(request: Request) -> Principal:
        if app.auth_mode is AuthMode.NONE:
            return DEV_PRINCIPAL
        name = request.headers.get(FORWARDED_USER, "").strip()
        if not name or len(name) > MAX_NAME_LENGTH:
            raise ApiError(401, "unauthenticated")
        user_id = member_id(name)
        role = await app.members.role_of(user_id)
        if role is None:
            raise ApiError(401, "unauthenticated")
        return Principal(user_id=user_id, name=name, role=role)

    return current_principal
