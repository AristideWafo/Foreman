"""Comptes, équipes et invitations : types et règles pures (aucune E/S).

Les invariants qui exigent la base (dernier org_admin, dernier admin d'équipe) sont appliqués par
le store, dans la transaction ; ici vivent les règles sans état.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from foreman.core.identity import ROLES, Role

PASSWORD_MIN: Final = 12
PASSWORD_MAX: Final = 128
MAX_INVITER_DEPTH: Final = 10
ADMIN_ROLES: Final[frozenset[Role]] = frozenset({"team_admin", "org_admin"})


class AccountError(Exception):
    """Refus de domaine. Le message est générique : jamais d'identifiant ni de détail interne."""


class LastAdmin(AccountError):
    """L'opération laisserait l'organisation sans org_admin actif (409)."""


class LastTeamAdmin(AccountError):
    """L'opération laisserait une équipe non personnelle sans admin actif (409)."""


class ElevationDenied(AccountError):
    """On n'accorde jamais un rôle supérieur au sien (403)."""


class NotFound(AccountError):
    """Compte, équipe ou membre absent."""


class Conflict(AccountError):
    """Doublon : e-mail, nom d'équipe ou appartenance déjà présents (409)."""


class InvalidInvitation(AccountError):
    """Invitation inconnue, expirée, déjà utilisée, ou e-mail différent (opaque)."""


class InvalidPassword(AccountError):
    """Longueur hors des bornes."""


class PersonalTeam(AccountError):
    """Une équipe personnelle n'a qu'un membre : pas d'ajout ni d'invitation (409)."""


class InvalidInviterChain(AccountError):
    """Chaîne `invited_by` cyclique ou trop profonde."""


@dataclass(frozen=True, slots=True)
class Account:
    id: UUID
    email: str
    name: str
    disabled_at: datetime | None = None
    invited_by: UUID | None = None


@dataclass(frozen=True, slots=True)
class Team:
    id: UUID
    name: str
    personal: bool = False


@dataclass(frozen=True, slots=True)
class Invitation:
    id: UUID
    email: str
    team_id: UUID | None
    role: Role
    invited_by: UUID
    expires_at: datetime
    used_at: datetime | None = None


def rank(role: Role) -> int:
    return ROLES.index(role)


def can_grant(actor: Role | None, role: Role) -> bool:
    """Anti-élévation : rôle accordé <= rôle de l'auteur. Seul un org_admin crée un org_admin."""
    return actor is not None and rank(role) <= rank(actor)


def require_grant(actor: Role | None, role: Role) -> None:
    if not can_grant(actor, role):
        raise ElevationDenied("droits insuffisants")


def validate_password(password: str) -> None:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise InvalidPassword(f"{PASSWORD_MIN} à {PASSWORD_MAX} caractères requis")


def validate_inviter_chain(
    start: UUID, parent_of: Mapping[UUID, UUID | None], max_depth: int = MAX_INVITER_DEPTH
) -> None:
    """Remonte `invited_by` depuis `start` : borné en profondeur, ensemble des vus anti-cycle.

    Un maillon absent de `parent_of` est une racine (le store ne charge que ce qui est utile).
    """
    seen: set[UUID] = set()
    current: UUID | None = start
    while current is not None:
        if current in seen or len(seen) >= max_depth:
            raise InvalidInviterChain("chaîne d'invitation invalide")
        seen.add(current)
        current = parent_of.get(current)


class AccountStore(Protocol):
    """Port de persistance des comptes. Les jetons et mots de passe n'y entrent que hachés."""

    async def create_account(
        self,
        email: str,
        name: str,
        password_hash: str | None,
        *,
        invited_by: UUID | None = None,
        role: Role = "team_admin",
    ) -> Account:
        """Compte + équipe personnelle (l'intéressé en est admin, ou `org_admin` si `role` l'est).

        Appelant de confiance (amorçage) : l'élévation se vérifie dans `accept_invitation`.
        """
        ...

    async def create_team(self, name: str, first_admin: UUID) -> Team: ...

    async def add_member(self, team_id: UUID, user_id: UUID, role: Role, actor: UUID) -> None: ...

    async def change_role(self, team_id: UUID, user_id: UUID, role: Role, actor: UUID) -> None: ...

    async def remove_member(self, team_id: UUID, user_id: UUID, actor: UUID) -> None: ...

    async def disable_account(self, user_id: UUID, actor: UUID) -> None: ...

    async def create_invitation(
        self,
        token_hash: str,
        email: str,
        team_id: UUID | None,
        role: Role,
        invited_by: UUID,
        expires_at: datetime,
    ) -> Invitation: ...

    async def accept_invitation(
        self, token_hash: str, email: str, name: str, password_hash: str, now: datetime
    ) -> Account:
        """Consomme l'invitation et crée le compte dans une transaction (tout ou rien)."""
        ...
