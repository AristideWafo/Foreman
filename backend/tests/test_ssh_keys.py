"""Clé SSH par serveur : stockée via le magasin de secrets, seule la clé publique sort."""

import os

import pytest

from foreman.core.secrets import SecretError
from foreman.infra.secrets import InMemorySecretStore, Keyring
from foreman.infra.ssh_keys import KIND, SshKeys, secret_id


async def test_relecture_identique_et_export_public_seul() -> None:
    store = InMemorySecretStore(Keyring.of(os.urandom(32)))
    keys = SshKeys(store)
    pub = await keys.ensure("prod", "srv1", created_by="admin")
    private = (await keys.private_key("prod", "srv1")).get_secret_value()
    assert pub.startswith("ssh-ed25519 ") and "PRIVATE" not in pub
    assert await keys.ensure("prod", "srv1", created_by="admin") == pub  # idempotent
    assert await keys.public_key("prod", "srv1") == pub
    sid = secret_id("prod", "srv1")
    assert b"PRIVATE" not in store.rows[sid][1].ciphertext  # chiffrée au repos
    assert (await store.get(sid, KIND)).get_secret_value() == private  # relecture identique
    assert (
        await keys.ensure("dev", "srv1", created_by="admin") != pub
    )  # une paire par environnement
    with pytest.raises(SecretError):
        await keys.public_key("prod", "inconnu")
