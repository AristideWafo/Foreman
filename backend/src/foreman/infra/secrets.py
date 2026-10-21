"""Chiffrement AES-256-GCM des secrets et fake en mémoire.

Le texte clair n'existe que dans `seal`/`open_sealed`. Les stores (mémoire ici, PostgreSQL dans
`infra/db/secrets.py`) ne gardent que `SealedSecret`.
"""

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from foreman.core.secrets import SecretError

KEY_BYTES = 32
NONCE_BYTES = 12


def key_id_of(key: bytes) -> str:
    """Identifiant public d'une clé : condensat tronqué, sans valeur exploitable."""
    return hashlib.sha256(key).hexdigest()[:8]


@dataclass(frozen=True, slots=True)
class Keyring:
    """Clés connues (id -> octets) et clé active. Les anciennes servent à relire avant rotation."""

    keys: Mapping[str, bytes] = field(repr=False)
    active: str

    def __post_init__(self) -> None:
        if self.active not in self.keys or any(len(k) != KEY_BYTES for k in self.keys.values()):
            raise SecretError("Trousseau de clés invalide.")

    @classmethod
    def of(cls, *keys: bytes) -> "Keyring":
        """Trousseau dont la dernière clé est active."""
        return cls({key_id_of(k): k for k in keys}, key_id_of(keys[-1]))


@dataclass(frozen=True, slots=True)
class SealedSecret:
    key_id: str
    nonce: bytes
    ciphertext: bytes


def _aad(secret_id: str, kind: str) -> bytes:
    return f"{secret_id}\x00{kind}".encode()


def seal(ring: Keyring, secret_id: str, kind: str, value: SecretStr) -> SealedSecret:
    nonce = os.urandom(NONCE_BYTES)
    plain = value.get_secret_value().encode()
    data = AESGCM(ring.keys[ring.active]).encrypt(nonce, plain, _aad(secret_id, kind))
    return SealedSecret(ring.active, nonce, data)


def open_sealed(ring: Keyring, secret_id: str, kind: str, row: SealedSecret) -> SecretStr:
    key = ring.keys.get(row.key_id)
    if key is None:
        raise SecretError("Secret illisible.")
    try:
        plain = AESGCM(key).decrypt(row.nonce, row.ciphertext, _aad(secret_id, kind))
    except InvalidTag:
        raise SecretError("Secret illisible.") from None
    return SecretStr(plain.decode())


class InMemorySecretStore:
    """Fake nommé pour les tests : mêmes règles de chiffrement que la production."""

    def __init__(self, ring: Keyring) -> None:
        self.ring = ring
        self.rows: dict[str, tuple[str, SealedSecret]] = {}  # id -> (kind, ligne chiffrée)

    async def put(self, secret_id: str, kind: str, value: SecretStr, *, created_by: str) -> None:
        self.rows[secret_id] = (kind, seal(self.ring, secret_id, kind, value))

    async def get(self, secret_id: str, kind: str) -> SecretStr | None:
        row = self.rows.get(secret_id)
        return None if row is None else open_sealed(self.ring, secret_id, kind, row[1])

    async def delete(self, secret_id: str) -> bool:
        return self.rows.pop(secret_id, None) is not None

    async def exists(self, secret_id: str) -> bool:
        return secret_id in self.rows

    async def rotate(self) -> int:
        stale = {sid: kr for sid, kr in self.rows.items() if kr[1].key_id != self.ring.active}
        for sid, (kind, row) in stale.items():
            clear = open_sealed(self.ring, sid, kind, row)
            self.rows[sid] = (kind, seal(self.ring, sid, kind, clear))
        return len(stale)


class KeyFile:
    """Clés maîtres dans un fichier 0600 d'un volume dédié : une clé hexadécimale par ligne,
    la dernière est active. Relu quand le fichier change (rotation faite par la CLI)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._ring: Keyring | None = None
        self._mtime = 0

    def exists(self) -> bool:
        return self.path.is_file()

    def current(self) -> Keyring:
        try:
            mtime = self.path.stat().st_mtime_ns
        except OSError:
            raise SecretError("Clé maître absente.") from None
        if self._ring is None or mtime != self._mtime:
            try:
                keys = [bytes.fromhex(x) for x in self.path.read_text().split()]
                self._ring = Keyring.of(*keys)
            except (OSError, ValueError, IndexError):
                raise SecretError("Clé maître illisible.") from None
            self._mtime = mtime
        return self._ring

    def create(self) -> None:
        """Première clé, créée sans écraser : échoue si le fichier existe déjà."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(os.urandom(KEY_BYTES).hex() + "\n")

    def add_key(self) -> None:
        """Ajoute une clé active en gardant les anciennes (écriture atomique, 0600)."""
        text = self.path.read_text().rstrip("\n") + "\n" + os.urandom(KEY_BYTES).hex() + "\n"
        self._replace(text)

    def keep_only_active(self) -> None:
        self._replace(self.path.read_text().split()[-1] + "\n")

    def _replace(self, text: str) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(self.path)
