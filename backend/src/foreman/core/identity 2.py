"""Identité de l'appelant : rôles de la matrice de droits (contrat figé v1)."""

from dataclasses import dataclass
from typing import Final, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict

Role = Literal["developer", "team_admin", "org_admin"]
ROLES: Final[tuple[Role, ...]] = ("developer", "team_admin", "org_admin")
_MEMBER_NAMESPACE: Final = uuid5(NAMESPACE_URL, "https://foreman.local/members")


def member_id(name: str) -> UUID:
    """Identifiant stable d'un membre de développement : le même nom donne le même UUID."""
    return uuid5(_MEMBER_NAMESPACE, name)


@dataclass(frozen=True, slots=True)
class Member:
    name: str
    role: Role
    id: UUID | None = None  # explicite pour `dev` (mode `none`) ; sinon dérivé du nom

    @property
    def user_id(self) -> UUID:
        return self.id or member_id(self.name)


class Principal(BaseModel):
    """Appelant authentifié. `user_id` vient du serveur, jamais du corps d'une requête."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    name: str
    role: Role
