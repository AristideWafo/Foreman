"""Vrai GitLab (transport simulé, aucun réseau) : fuite de jeton, faux ou vrai, fichiers."""

import base64
import logging
import os

import httpx2
import pytest
from pydantic import SecretStr

from foreman.bootstrap.adapters import ConfiguredGitLab, build_adapters
from foreman.core.connector_state import CONNECTOR_TOKEN_KIND, connector_secret_id
from foreman.core.ports import AdapterError, PermissionMissing
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.secrets import InMemorySecretStore, Keyring
from foreman.integrations.gitlab.adapter import RealGitLab
from foreman.integrations.gitlab.client import GitLabClient
from foreman.integrations.gitlab.simulated import SimulatedGitLab

TOKEN = "glpat-" + "A" * 24
AWS_KEY = "AKIA" + "B" * 16


class GitLabTransport(httpx2.AsyncBaseTransport):
    """Faux gitlab.com : sert `routes` (chemin -> (statut, JSON ou texte)) et garde les requêtes."""

    def __init__(self, routes: dict[str, tuple[int, object]]) -> None:
        self.routes = routes
        self.seen: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(request)
        status, body = self.routes.get(request.url.path, (404, {}))
        if isinstance(body, str):
            return httpx2.Response(status, text=body)
        return httpx2.Response(status, json=body)


async def store_with(*names: str) -> InMemorySecretStore:
    store = InMemorySecretStore(Keyring.of(os.urandom(32)))
    for name in names:
        await store.put(
            connector_secret_id("gitlab", name),
            CONNECTOR_TOKEN_KIND,
            SecretStr(TOKEN),
            created_by="test",
        )
    return store


async def real_with(routes: dict[str, tuple[int, object]]) -> tuple[RealGitLab, GitLabTransport]:
    transport = GitLabTransport(routes)
    return RealGitLab(GitLabClient(await store_with("read"), transport=transport), 1000), transport


async def test_a_500_quoting_the_token_leaks_nothing_and_secret_fields_are_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    project = {"id": 7, "name": "api", "runners_token": "GR1348941abc", "variables": [{"v": 1}]}
    real, transport = await real_with(
        {
            "/api/v4/projects/1": (500, f"boom PRIVATE-TOKEN: {TOKEN}"),
            "/api/v4/projects/2": (200, project),
        }
    )
    with pytest.raises(AdapterError) as failure:
        await real.execute("gitlab.get_project", {"project_id": 1}, "k")
    assert TOKEN not in str(failure.value) and TOKEN not in caplog.text
    assert failure.value.__cause__ is None and failure.value.diagnostic is not None
    assert failure.value.diagnostic.code == "gitlab_error"
    out = (await real.execute("gitlab.get_project", {"project_id": 2}, "k")).output
    assert "runners_token" not in out and "variables" not in out and out["id"] == 7
    assert all(TOKEN not in str(r.url) for r in transport.seen)
    assert transport.seen[0].headers["PRIVATE-TOKEN"] == TOKEN


async def test_configured_gitlab_picks_fake_or_real_without_ever_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)
    catalog = load_catalog(catalog_dir_from_env(), environment="staging")
    group = {"parent_group_id": 1000, "name": "Safe Eat", "path": "safe-eat"}

    async def configured(*tokens: str) -> tuple[ConfiguredGitLab, GitLabTransport]:
        transport = GitLabTransport({"/api/v4/groups": (500, {})})
        store = await store_with(*tokens)
        real = RealGitLab(GitLabClient(store, transport=transport), 1000)
        return ConfiguredGitLab(SimulatedGitLab(), real, store), transport

    none, transport = await configured()
    assert (await none.execute("gitlab.create_group", group, "k")).created is True
    assert transport.seen == []  # le faux a répondu

    read_only, transport = await configured("read")
    with pytest.raises(PermissionMissing):  # écriture sans jeton d'écriture : jamais le faux
        await read_only.execute("gitlab.create_group", group, "k")
    with pytest.raises(AdapterError):  # le vrai échoue (500) : pas de repli sur le faux
        await read_only.execute("gitlab.list_groups", {}, "k")
    assert len(transport.seen) == 1

    assert isinstance(build_adapters(catalog, await store_with())["gitlab"], ConfiguredGitLab)
    monkeypatch.setenv("CI", "true")
    assert isinstance(build_adapters(catalog, await store_with("read"))["gitlab"], SimulatedGitLab)


async def test_read_file_refuses_secrets_and_binaries_then_truncates_and_masks() -> None:
    def blob(raw: bytes, size: int | None = None) -> tuple[int, object]:
        content = base64.b64encode(raw).decode()
        return 200, {"size": size or len(raw), "encoding": "base64", "content": content}

    text = f"aws_access_key_id = {AWS_KEY}\n" + "x" * 5000
    prefix = "/api/v4/projects/1/repository/files/"
    real, transport = await real_with(
        {
            prefix + "bin.dat": blob(b"\x00\x01\x02"),
            prefix + "big.txt": blob(b"a", size=70_000),
            prefix + "app.txt": blob(text.encode()),
        }
    )
    base = {"project_id": 1, "ref": "main"}
    refused = (".env", "conf/.env.prod", "tls/server.pem", "k.key", "id_rsa", "bin.dat", "big.txt")
    for path in refused:
        with pytest.raises(AdapterError):
            await real.execute("gitlab.read_file", {**base, "path": path}, "k")
    assert not any("env" in r.url.path or "pem" in r.url.path for r in transport.seen)
    out = (await real.execute("gitlab.read_file", {**base, "path": "app.txt"}, "k")).output
    content = out["content"]
    assert isinstance(content, str) and AWS_KEY not in content
    assert len(content) <= 3000 and out["truncated"] is True
