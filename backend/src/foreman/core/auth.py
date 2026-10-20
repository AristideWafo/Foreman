"""Authentification par mot de passe : jetons, sessions et amorçage de l'administrateur.

Seuls des condensats de jetons sont stockés. Le rôle d'une session est relu en base à chaque
requête (jamais copié dans la session).
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from foreman.core.accounts import AccountError, AccountStore
from foreman.core.identity import Role

SESSION_TTL: Final = timedelta(hours=12)  # glissante : repoussée à chaque requête
ADMIN_INVITATION_TTL: Final = timedelta(hours=1)
INVITATION_TTL: Final = timedelta(days=7)


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 32 octets aléatoires


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_for(session_token: str) -> str:
    """Jeton CSRF de la session, dérivé du jeton de session (rendu par `GET /me`)."""
    return hashlib.sha256(b"csrf:" + session_token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Credentials:
    user_id: UUID
    password_hash: str | None
    disabled: bool


@dataclass(frozen=True, slots=True)
class SessionInfo:
    user_id: UUID
    name: str
    role: Role
    csrf_hash: str


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str | None, password: str) -> bool:
        """Faux si le condensat est absent (même coût : pas d'énumération par le temps)."""
        ...


class AuthStore(Protocol):
    async def credentials(self, email: str) -> Credentials | None: ...

    async def open_session(
        self, id_hash: str, csrf_hash: str, user_id: UUID, now: datetime
    ) -> None: ...

    async def session(self, id_hash: str, now: datetime) -> SessionInfo | None:
        """Session valide d'un compte actif, repoussée de `SESSION_TTL` ; sinon `None`."""
        ...

    async def close_session(self, id_hash: str) -> None: ...

    async def record_login(self, user_id: UUID | None, success: bool) -> None:
        """Audit sans secret ni e-mail."""
        ...

    async def has_admin(self) -> bool:
        """Au moins un org_admin actif."""
        ...


async def create_admin_invitation(
    accounts: AccountStore, auth: AuthStore, email: str, now: datetime
) -> str:
    """Crée (ou retrouve, tant qu'il n'a pas de mot de passe) l'org_admin ; renvoie le jeton
    d'invitation de premier mot de passe, à usage unique, valable `ADMIN_INVITATION_TTL`."""
    email = email.strip().lower()
    known = await auth.credentials(email)
    if known is None:
        account = await accounts.create_account(email, email.split("@")[0], None, role="org_admin")
        user_id = account.id
    elif known.password_hash is not None or known.disabled:
        raise AccountError("compte déjà actif")
    else:
        user_id = known.user_id
    token = new_token()
    # L'invitation est « de soi à soi » : le store vérifie que l'intéressé est bien org_admin.
    await accounts.create_invitation(
        token_hash(token), email, None, "org_admin", user_id, now + ADMIN_INVITATION_TTL
    )
    return token
