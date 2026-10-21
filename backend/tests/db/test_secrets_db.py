"""Magasin de secrets en PostgreSQL réel : chiffrement, refus au démarrage, rotation (#256)."""

import logging
import os
import stat
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import SecretStr

from foreman.bootstrap.configure import Profile, configure
from foreman.bootstrap.secrets import rotate_master_key
from foreman.config.env import ENV_DATABASE_URL, ENV_SECRETS_KEY_FILE
from foreman.core.secrets import SecretError
from foreman.infra.db import tables as t
from foreman.infra.db.engine import make_engine
from foreman.infra.db.migrate import upgrade_head
from foreman.infra.db.secrets import PostgresSecretStore
from foreman.infra.secrets import KeyFile

TOKEN = "glpat-tres-secret"  # noqa: S105 - valeur factice


@pytest.fixture
async def store(blank_database_url: str, tmp_path: Path) -> object:
    upgrade_head(blank_database_url)
    keys = KeyFile(tmp_path / "k" / "master.key")
    keys.create()
    engine = make_engine(blank_database_url)
    yield PostgresSecretStore(engine, keys.current), keys, engine
    await engine.dispose()


async def rows(engine: sa.ext.asyncio.AsyncEngine) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.select(t.secrets))).all())


async def test_relecture_identique_texte_clair_absent_de_la_base_et_des_logs(
    store: tuple[PostgresSecretStore, KeyFile, sa.ext.asyncio.AsyncEngine],
    caplog: pytest.LogCaptureFixture,
) -> None:
    s, _, engine = store
    caplog.set_level(logging.DEBUG)
    await s.put("gitlab", "token", SecretStr(TOKEN), created_by="admin")
    assert (await s.get("gitlab", "token")) is not None
    got = await s.get("gitlab", "token")
    assert got is not None and got.get_secret_value() == TOKEN
    assert await s.exists("gitlab") and not await s.exists("autre")
    (row,) = await rows(engine)
    assert TOKEN.encode() not in b"".join(v for v in row if isinstance(v, bytes | memoryview))
    assert TOKEN not in " ".join(str(v) for v in row) and TOKEN not in caplog.text
    assert await s.delete("gitlab") and not await s.exists("gitlab")


async def test_aad_ou_cle_incorrecte_echoue(
    store: tuple[PostgresSecretStore, KeyFile, sa.ext.asyncio.AsyncEngine], tmp_path: Path
) -> None:
    s, _, engine = store
    await s.put("gitlab", "token", SecretStr(TOKEN), created_by="admin")
    with pytest.raises(SecretError):
        await s.get("gitlab", "llm")  # autre `kind`
    async with engine.begin() as conn:  # ligne recopiée sous un autre identifiant
        await conn.execute(sa.update(t.secrets).values(id="usurpe"))
    with pytest.raises(SecretError):
        await s.get("usurpe", "token")
    other = KeyFile(tmp_path / "autre" / "master.key")
    other.create()
    with pytest.raises(SecretError):
        await PostgresSecretStore(engine, other.current).get("usurpe", "token")


async def test_rotation_rechiffre_tout(
    store: tuple[PostgresSecretStore, KeyFile, sa.ext.asyncio.AsyncEngine],
) -> None:
    s, keys, engine = store
    await s.put("a", "token", SecretStr("1"), created_by="admin")
    await s.put("b", "llm", SecretStr("2"), created_by="admin")
    before = {r.id: r.ciphertext for r in await rows(engine)}
    assert await rotate_master_key(keys, s, prune=True) == 2
    after = await rows(engine)
    assert all(r.key_id == keys.current().active and r.rotated_at for r in after)
    assert {r.id: r.ciphertext for r in after} != before
    assert len(keys.path.read_text().split()) == 1  # anciennes clés retirées
    assert (await s.get("b", "llm")) is not None


async def test_demarrage_cree_la_cle_puis_refuse_sans_elle_si_des_secrets_existent(
    blank_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_path = tmp_path / "vol" / "master.key"
    monkeypatch.setenv(ENV_DATABASE_URL, blank_database_url)
    monkeypatch.setenv(ENV_SECRETS_KEY_FILE, os.fspath(key_path))
    first = configure(Profile.WEB)
    await first.lifecycle.start()
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600
    await first.secrets.put("llm", "llm_key", SecretStr("sk-x"), created_by="admin")
    await first.lifecycle.stop()

    key_path.unlink()  # volume perdu ou non monté
    second = configure(Profile.WEB)
    with pytest.raises(RuntimeError):
        await second.lifecycle.start()
    await second.lifecycle.stop()
    assert not key_path.exists()  # aucune nouvelle clé générée
