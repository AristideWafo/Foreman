"""Port du magasin de secrets (jetons, clés d'API saisis dans l'interface).

Un secret est identifié par `secret_id` et typé par `kind` ; les deux sont liés au chiffrement
(données authentifiées) : une ligne recopiée sous un autre identifiant ne se déchiffre pas.
"""

from typing import Protocol

from pydantic import SecretStr

__all__ = ["SecretError", "SecretStore", "SecretStr"]


class SecretError(Exception):
    """Chiffrement impossible ou déchiffrement refusé. Message opaque : ni clé, ni identifiant."""


class SecretStore(Protocol):
    async def put(self, secret_id: str, kind: str, value: SecretStr, *, created_by: str) -> None:
        """Crée ou remplace le secret `secret_id`."""
        ...

    async def get(self, secret_id: str, kind: str) -> SecretStr | None:
        """`None` si absent ; `SecretError` si le déchiffrement échoue."""
        ...

    async def delete(self, secret_id: str) -> bool: ...

    async def exists(self, secret_id: str) -> bool: ...

    async def rotate(self) -> int:
        """Rechiffre tout avec la clé active ; renvoie le nombre de secrets traités."""
        ...
