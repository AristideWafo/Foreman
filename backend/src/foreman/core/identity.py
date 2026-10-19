"""Identité de l'appelant : rôles de la matrice de droits (contrat figé v1)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Role = Literal["developer", "team_admin", "org_admin"]


class Principal(BaseModel):
    """Appelant authentifié. `user_id` vient du serveur, jamais du corps d'une requête."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    name: str
    role: Role
