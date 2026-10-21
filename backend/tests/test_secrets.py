"""Magasin de secrets : chiffrement AES-256-GCM (règles communes à la mémoire et à PostgreSQL)."""

import os

import pytest
from pydantic import SecretStr

from foreman.core.secrets import SecretError
from foreman.infra.secrets import InMemorySecretStore, Keyring, open_sealed, seal

OLD, NEW = os.urandom(32), os.urandom(32)
TOKEN = "glpat-tres-secret"  # noqa: S105 - valeur factice


def test_relecture_identique_et_texte_clair_absent() -> None:
    ring = Keyring.of(OLD)
    row = seal(ring, "gitlab", "token", SecretStr(TOKEN))
    assert TOKEN.encode() not in row.ciphertext
    assert TOKEN not in repr(SecretStr(TOKEN)) and TOKEN not in repr(ring)
    assert open_sealed(ring, "gitlab", "token", row).get_secret_value() == TOKEN


def test_aad_ou_cle_incorrecte_refuse() -> None:
    row = seal(Keyring.of(OLD), "gitlab", "token", SecretStr(TOKEN))
    for ring, sid, kind in [
        (Keyring.of(OLD), "autre", "token"),
        (Keyring.of(OLD), "gitlab", "llm"),
        (Keyring.of(NEW), "gitlab", "token"),
    ]:
        with pytest.raises(SecretError):
            open_sealed(ring, sid, kind, row)


async def test_rotation_rechiffre_tout() -> None:
    store = InMemorySecretStore(Keyring.of(OLD))
    await store.put("a", "token", SecretStr("1"), created_by="admin")
    await store.put("b", "llm", SecretStr("2"), created_by="admin")
    store.ring = Keyring.of(OLD, NEW)  # NEW devient active, OLD sert à relire
    assert await store.rotate() == 2
    assert {row.key_id for _, row in store.rows.values()} == {store.ring.active}
    only_new = Keyring.of(NEW)
    for sid, (kind, row) in store.rows.items():
        assert open_sealed(only_new, sid, kind, row).get_secret_value() in {"1", "2"}
