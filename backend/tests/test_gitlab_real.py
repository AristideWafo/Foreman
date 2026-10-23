"""Vrai GitLab (transport simulé, aucun réseau) : fuite de jeton, faux ou vrai, fichiers."""

import base64
import json
import logging
import os

import httpx2
import pytest
from pydantic import JsonValue, SecretStr

from foreman.bootstrap.adapters import ConfiguredGitLab, build_adapters
from foreman.core.connector_state import CONNECTOR_TOKEN_KIND, connector_secret_id
from foreman.core.gateway.port import ReadCall
from foreman.core.ports import AdapterError, ForeignResource, PermissionMissing
from foreman.core.store import DEV_USER_ID
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.secrets import InMemorySecretStore, Keyring
from foreman.integrations.gitlab.adapter import RealGitLab
from foreman.integrations.gitlab.client import GitLabClient
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from test_gateway import make_world

TOKEN = "glpat-" + "A" * 24


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
    return RealGitLab(GitLabClient(await store_with("read"), transport=transport)), transport


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


async def test_without_a_token_or_with_a_read_token_only_nothing_falls_back_to_the_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CI", raising=False)
    catalog = load_catalog(catalog_dir_from_env(), environment="staging")
    group = {"parent_group_id": 1000, "name": "Safe Eat", "path": "safe-eat"}

    async def configured(*tokens: str) -> tuple[ConfiguredGitLab, GitLabTransport]:
        transport = GitLabTransport({"/api/v4/groups": (500, {})})
        store = await store_with(*tokens)
        return ConfiguredGitLab(
            RealGitLab(GitLabClient(store, transport=transport)), store
        ), transport

    none, transport = await configured()
    for tool, params in (("gitlab.list_groups", {}), ("gitlab.create_group", group)):
        with pytest.raises(PermissionMissing):  # pas de faux : ni lecture ni écriture
            await none.execute(tool, params, "k")
    assert transport.seen == []

    read_only, transport = await configured("read")
    with pytest.raises(PermissionMissing):  # écriture sans jeton d'écriture
        await read_only.execute("gitlab.create_group", group, "k")
    with pytest.raises(AdapterError):  # le vrai échoue (500) : pas de repli
        await read_only.execute("gitlab.list_groups", {}, "k")
    assert len(transport.seen) == 1

    store = await store_with()
    assert isinstance(build_adapters(catalog, store)["gitlab"], ConfiguredGitLab)
    assert isinstance(build_adapters(catalog, store, force_fake=True)["gitlab"], SimulatedGitLab)
    monkeypatch.setenv("CI", "true")
    assert isinstance(build_adapters(catalog, store)["gitlab"], SimulatedGitLab)


async def test_read_file_refuses_secrets_and_binaries_and_cuts_under_the_gateway_limit() -> None:
    def blob(raw: bytes, size: int | None = None) -> tuple[int, object]:
        content = base64.b64encode(raw).decode()
        return 200, {"size": size or len(raw), "encoding": "base64", "content": content}

    prefix = "/api/v4/projects/1/repository/files/"
    real, transport = await real_with(
        {
            prefix + "bin.dat": blob(b"\x00\x01\x02"),
            prefix + "big.txt": blob(b"a", size=70_000),
            prefix + "app.txt": blob(("x" * 5000).encode()),
        }
    )
    base = {"project_id": 1, "ref": "main"}
    refused = (".env", "conf/.env.prod", "tls/server.pem", "k.key", "id_rsa", "id_ed25519")
    refused += ("a.tfstate", "b.tfvars", ".npmrc", ".git-credentials", "bin.dat", "big.txt")
    for path in refused:
        with pytest.raises(AdapterError):
            await real.execute("gitlab.read_file", {**base, "path": path}, "k")
    assert [r.url.path for r in transport.seen if "app" in r.url.path] == []
    seen_before = len(transport.seen)
    out = (await real.execute("gitlab.read_file", {**base, "path": "app.txt"}, "k")).output
    assert len(str(out["content"])) == 480 and out["truncated"] is True
    assert len(transport.seen) == seen_before + 1


PEM = (
    "-----BEGIN RSA "
    + "PRIVATE KEY-----\n"
    + "\n".join("MIIEowIBAAKCAQEA" + "Zx9q" * 12 for _ in range(3))
    + "\n-----END RSA "
    + "PRIVATE KEY-----\n"
)


async def read_through_gateway(
    routes: dict[str, tuple[int, object]], tool: str, params: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    store = await store_with("read")
    real = RealGitLab(GitLabClient(store, transport=GitLabTransport(routes)))
    world = make_world(gitlab=real)
    project = (await world.projects.create("p")).id
    return await world.gateway.read(ReadCall(project, DEV_USER_ID, tool, params))


async def test_a_pem_in_a_txt_comes_out_of_the_gateway_without_its_body() -> None:
    body = {
        "size": len(PEM),
        "encoding": "base64",
        "content": base64.b64encode(PEM.encode()).decode(),
    }
    route = "/api/v4/projects/1/repository/files/notes.txt"
    out = await read_through_gateway(
        {route: (200, body)}, "gitlab.read_file", {"project_id": 1, "path": "notes.txt", "ref": "m"}
    )
    assert "Zx9qZx9q" not in str(out["content"]) and "MIIEowIBAAKCAQEA" not in str(out["content"])


async def test_a_full_page_of_realistic_items_survives_the_gateway_size_limit() -> None:
    long_path = "organisation-plateforme/equipe-paiements/services/service-de-facturation-"
    projects = [
        {
            "id": 10_000_000 + i,
            "name": f"service-facturation-{i}",
            "path_with_namespace": f"{long_path}{i}",
            "web_url": f"https://gitlab.com/{long_path}{i}",
            "default_branch": "main",
            "last_activity_at": "2026-10-21T08:15:42.123Z",
            "runners_token": "x" * 40,
        }
        for i in range(10)
    ]
    issues = [
        {
            "iid": i,
            "title": "Corriger le calcul de la TVA sur les factures avoisinant minuit " + str(i),
            "state": "opened",
            "author": {"username": "jdupont"},
            "labels": [f"label-{j}-{'l' * 20}" for j in range(2)],
            "web_url": f"https://gitlab.com/{long_path}0/-/issues/{i}",
        }
        for i in range(10)
    ]
    routes: dict[str, tuple[int, object]] = {
        "/api/v4/groups/5/projects": (200, projects),
        "/api/v4/projects/1/issues": (200, issues),
    }
    listed = await read_through_gateway(routes, "gitlab.list_projects", {"group_id": 5})
    assert "truncated" not in listed and len(listed["projects"]) == 10  # type: ignore[arg-type]
    found = await read_through_gateway(
        routes, "gitlab.list_issues", {"project_id": 1, "state": "all"}
    )
    assert "truncated" not in found and len(found["issues"]) == 10  # type: ignore[arg-type]


class WritableGitLab(httpx2.AsyncBaseTransport):
    """gitlab.com minimal avec état : jeton `write` de niveau `level` sur le groupe parent 7."""

    def __init__(self, level: int, existing: dict[str, str] | None = None) -> None:
        self.level = level
        self.groups = dict(existing or {})  # full_path -> description
        self.posts: list[httpx2.Request] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if request.method == "POST":
            self.posts.append(request)
            body = json.loads(request.content)
            full = f"team/{body['path']}"
            self.groups[full] = body["description"]
            return httpx2.Response(201, json={"id": 99, "web_url": "https://gitlab.com/" + full})
        if path.endswith("/personal_access_tokens/self"):
            return httpx2.Response(200, json={"user_id": 5, "scopes": ["api"], "active": True})
        if path.endswith("/groups/7/members/all/5"):
            return httpx2.Response(200, json={"access_level": self.level})
        if path.endswith("/groups/7"):
            return httpx2.Response(200, json={"full_path": "team"})
        description = self.groups.get(path.removeprefix("/api/v4/groups/"))
        if description is None:
            return httpx2.Response(404, json={})
        return httpx2.Response(
            200, json={"id": 99, "web_url": "https://gitlab.com/x", "description": description}
        )


async def writer(transport: WritableGitLab) -> RealGitLab:
    return RealGitLab(GitLabClient(await store_with("write"), transport=transport))


GROUP = {"parent_group_id": 7, "name": "Safe Eat", "path": "safe-eat"}


async def test_creation_needs_owner_of_the_parent_and_posts_nothing_otherwise() -> None:
    transport = WritableGitLab(level=40)  # Maintainer : refusé
    with pytest.raises(PermissionMissing):
        await (await writer(transport)).execute("gitlab.create_group", GROUP, "k")
    assert transport.posts == []


async def test_create_group_is_idempotent_and_never_adopts_a_foreign_group() -> None:
    transport = WritableGitLab(level=50, existing={"team/legacy": "groupe historique"})
    real = await writer(transport)
    first = await real.execute("gitlab.create_group", GROUP, "k")
    second = await real.execute("gitlab.create_group", GROUP, "k")
    assert (first.created, second.created) == (True, False)
    assert len(transport.posts) == 1 and "managed-by=foreman" in transport.groups["team/safe-eat"]
    with pytest.raises(ForeignResource):
        await real.execute("gitlab.create_group", {**GROUP, "path": "legacy"}, "k")
    assert len(transport.posts) == 1
