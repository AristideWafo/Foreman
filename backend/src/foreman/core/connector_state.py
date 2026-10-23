"""État persisté d'un connecteur : statut de la dernière sonde et références des jetons.

Aucun jeton ici : `secret_refs` ne contient que des identifiants du magasin de secrets. Chaque
mutation écrit sa ligne d'audit dans la MÊME transaction (sans jeton).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from foreman.core.gateway.port import RightVerdict

ConnectorStatus = Literal["ok", "incomplete", "revoked"]
CredentialAction = Literal["credential.set", "credential.revoke", "credential.test", "model.set"]
CONNECTOR_TOKEN_KIND = "connector_token"  # noqa: S105 - type de secret, pas une valeur


def connector_secret_id(connector: str, token: str) -> str:
    """Identifiant, dans le magasin de secrets, du jeton `token` d'un connecteur."""
    return f"connector.{connector}.{token}"


@dataclass(frozen=True, slots=True)
class ConnectorState:
    status: ConnectorStatus
    rights: tuple[RightVerdict, ...]  # droits vérifiés par la dernière sonde
    last_probe_at: datetime | None


class ConnectorStore(Protocol):
    async def states(self) -> Mapping[str, ConnectorState]:
        """Un état par connecteur déjà connu (sondé ou configuré)."""
        ...

    async def save_probe(
        self,
        connector: str,
        declared: Mapping[str, list[str]],
        status: ConnectorStatus,
        rights: tuple[RightVerdict, ...],
        actor: UUID,
    ) -> None:
        """Enregistre le résultat d'une sonde (statut, droits vérifiés, date) + audit `.test`."""
        ...

    async def save_change(
        self,
        connector: str,
        declared: Mapping[str, list[str]],
        action: CredentialAction,
        secret_refs: Mapping[str, str | None],
        actor: UUID,
    ) -> None:
        """Pose ou retire des références de jetons (`credential.set` : statut `incomplete`, droits
        effacés ; `credential.revoke` : `revoked`) + audit. `model.set` n'altère que l'audit."""
        ...
