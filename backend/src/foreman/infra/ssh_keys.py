"""Paire ed25519 SSH par serveur et par environnement.

La clé privée n'existe en clair que dans ce module, le temps de la génération ou de la dérivation ;
elle ne vit durablement que dans le `SecretStore`. Seule la clé publique sort.
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from foreman.core.secrets import SecretError, SecretStore

KIND = "ssh_ed25519"


def secret_id(environment: str, server_id: str) -> str:
    return f"ssh:{environment}:{server_id}"


def _public_openssh(private_pem: SecretStr) -> str:
    loaded = serialization.load_ssh_private_key(private_pem.get_secret_value().encode(), None)
    pub = loaded.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return pub.decode()


class SshKeys:
    def __init__(self, store: SecretStore) -> None:
        self._store = store

    async def ensure(self, environment: str, server_id: str, *, created_by: str) -> str:
        """Crée la paire si absente (idempotent) et renvoie la clé publique OpenSSH."""
        sid = secret_id(environment, server_id)
        # shortcut: lecture puis écriture sans verrou, deux créations simultanées possibles ; à
        # verrouiller (upsert conditionnel) quand une route l'exposera (#260).
        if (pem := await self._store.get(sid, KIND)) is None:
            raw = Ed25519PrivateKey.generate().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
            pem = SecretStr(raw.decode())
            await self._store.put(sid, KIND, pem, created_by=created_by)
        return _public_openssh(pem)

    async def private_key(self, environment: str, server_id: str) -> SecretStr:
        """Réservé à l'adaptateur SSH (#52) ; jamais exposé par une route."""
        pem = await self._store.get(secret_id(environment, server_id), KIND)
        if pem is None:
            raise SecretError("Clé SSH introuvable.")
        return pem

    async def public_key(self, environment: str, server_id: str) -> str:
        """Clé publique OpenSSH ; `SecretError` si la paire n'existe pas."""
        return _public_openssh(await self.private_key(environment, server_id))
