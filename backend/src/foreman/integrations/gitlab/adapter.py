"""`RealGitLab` : lectures et créations (REST gitlab.com) et sondeur.

Sorties en LISTE D'AUTORISATION de champs : tout ce que GitLab renvoie en plus (runners_token,
variables, ...) est ignoré. Pagination imposée : `per_page=20`, `page` de 1 à 10.
"""

import asyncio
import base64
import binascii
import fnmatch
import json
import re
from collections.abc import Callable, Mapping
from typing import Final
from urllib.parse import parse_qsl, quote, urlsplit

from pydantic import JsonValue

from foreman.core.ports import (
    AdapterError,
    AdapterResult,
    ForeignResource,
    PermissionMissing,
    ProbeOutcome,
)
from foreman.integrations.gitlab.client import GitLabClient, gitlab_error

PER_PAGE: Final = 10  # la gateway borne une sortie à 4 Kio
MAX_PAGE: Final = 10
MAX_FILE_BYTES: Final = 64 * 1024
MAX_CONTENT_CHARS: Final = 480  # la gateway coupe toute chaîne à 500 caractères
MAX_TITLE: Final = 80
MAX_LIST_BYTES: Final = 3500  # sous les 4 Kio de la gateway (`MAX_OUTPUT_BYTES`)
_FORBIDDEN_FILES: Final = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "*.p12",
    "*.pfx",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "*.tfstate",
    "*.tfvars",
)
_STATES: Final = ("opened", "closed", "merged", "all")
_PLACEHOLDER: Final = re.compile(r"\{user_id\}")
MARKING: Final = "managed-by=foreman"
OWNER: Final = 50  # GitLab : 50 = Owner (40 = Maintainer)
_PAT_SELF: Final = "/personal_access_tokens/self"
_GROUP_PATH: Final = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
_PROJECT_PATH: Final = re.compile(r"[a-z0-9][a-z0-9-]{1,60}")

Obj = Mapping[str, JsonValue]


def _int(
    params: Mapping[str, JsonValue], key: str, *, low: int = 1, high: int | None = None
) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < low:
        raise AdapterError("paramètre invalide")
    if high is not None and value > high:
        raise AdapterError("paramètre invalide")
    return value


def _page(params: Mapping[str, JsonValue]) -> dict[str, str | int]:
    page = _int(params, "page", high=MAX_PAGE) if "page" in params else 1
    return {"per_page": PER_PAGE, "page": page}


def _filters(params: Mapping[str, JsonValue], *names: str) -> dict[str, str | int]:
    """Filtres facultatifs du schéma de l'outil, transmis tels quels (chaînes bornées)."""
    found: dict[str, str | int] = {}
    for name in names:
        value = params.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 255:
            raise AdapterError("paramètre invalide")
        if name == "state" and value not in _STATES:
            raise AdapterError("paramètre invalide")
        found[name] = value
    return found


def _list(data: JsonValue) -> list[Obj]:
    if not isinstance(data, list) or not all(isinstance(i, dict) for i in data):
        raise gitlab_error("bad_response")
    return [i for i in data if isinstance(i, dict)]


def _obj(data: JsonValue) -> Obj:
    if not isinstance(data, dict):
        raise gitlab_error("bad_response")
    return data


def _pick(item: Obj, fields: tuple[str, ...]) -> dict[str, JsonValue]:
    return {f: item.get(f) for f in fields}


def _text(value: JsonValue, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _author(item: Obj) -> str:
    author = item.get("author")
    return _text(author.get("username"), 40) if isinstance(author, dict) else ""


def _labels(item: Obj) -> list[JsonValue]:
    labels = item.get("labels")
    return [_text(x, 20) for x in labels[:5]] if isinstance(labels, list) else []


def _issue(item: Obj) -> dict[str, JsonValue]:
    return {
        "iid": item.get("iid"),
        "title": _text(item.get("title"), MAX_TITLE),
        "state": item.get("state"),
        "author": _author(item),
        "labels": _labels(item),
        "web_url": item.get("web_url"),
    }


def _mr(item: Obj) -> dict[str, JsonValue]:
    return {
        **_pick(item, ("iid",)),
        "title": _text(item.get("title"), MAX_TITLE),
        **_pick(item, ("state", "source_branch", "target_branch")),
        "author": _author(item),
        "web_url": item.get("web_url"),
    }


def _branch(item: Obj) -> dict[str, JsonValue]:
    commit = item.get("commit")
    short = commit.get("short_id") if isinstance(commit, dict) else None
    return {**_pick(item, ("name", "default", "protected")), "commit_short_id": short}


def _project_detail(item: Obj) -> dict[str, JsonValue]:
    return {
        **_pick(item, ("id", "name", "path_with_namespace", "web_url", "default_branch")),
        "visibility": item.get("visibility"),
        "description": _text(item.get("description"), 300),
        "open_issues_count": item.get("open_issues_count"),
    }


def _pipeline(item: Obj) -> dict[str, JsonValue]:
    return _pick(item, ("id", "status", "ref", "web_url", "created_at"))


def _forbidden(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in _FORBIDDEN_FILES)


class RealGitLab:
    """`ToolAdapter` + `ConnectorProber` sur gitlab.com. Jeton relu à chaque appel."""

    def __init__(self, client: GitLabClient) -> None:
        self._client = client
        self._write_lock = asyncio.Lock()  # « lire puis créer » d'une instance, sans course

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        # Lectures sans effet ; créations en « lire puis créer » : la clé est inutile.
        match tool:
            case "gitlab.create_group":
                return await self._create(params, group=True)
            case "gitlab.create_project":
                return await self._create(params, group=False)
            case "gitlab.list_groups":
                parent = params.get("parent_group_id")
                path = "/groups"
                if parent is not None:
                    path = f"/groups/{_int(params, 'parent_group_id')}/subgroups"
                return await self._collection(
                    path,
                    params,
                    "groups",
                    ("id", "name", "full_path", "web_url"),
                    _filters(params, "search"),
                )
            case "gitlab.list_projects":
                fields = (
                    "id",
                    "name",
                    "path_with_namespace",
                    "web_url",
                    "default_branch",
                    "last_activity_at",
                )
                path = f"/groups/{_int(params, 'group_id')}/projects"
                return await self._collection(
                    path, params, "projects", fields, _filters(params, "search")
                )
            case "gitlab.get_project":
                data, _ = await self._client.get(f"/projects/{_int(params, 'project_id')}")
                return AdapterResult(output=_project_detail(_obj(data)))
            case "gitlab.list_branches":
                return await self._project_list(
                    params, "repository/branches", "branches", _branch, _filters(params, "search")
                )
            case "gitlab.list_pipelines":
                return await self._project_list(
                    params, "pipelines", "pipelines", _pipeline, _filters(params, "ref", "status")
                )
            case "gitlab.list_issues":
                return await self._project_list(
                    params, "issues", "issues", _issue, _filters(params, "search", "state")
                )
            case "gitlab.list_merge_requests":
                return await self._project_list(
                    params, "merge_requests", "merge_requests", _mr, _filters(params, "state")
                )
            case "gitlab.read_file":
                return await self._read_file(params)
        raise gitlab_error("unsupported")

    async def _owner_check(self, parent_id: int) -> None:
        """Le jeton `write` doit être Owner du parent, vérifié À L'APPEL (pas de racine fixe)."""
        me, _ = await self._client.get(_PAT_SELF, tokens=("write",))
        user_id = _obj(me).get("user_id")
        if type(user_id) is not int:
            raise gitlab_error("bad_response")
        try:
            data, _ = await self._client.get(
                f"/groups/{parent_id}/members/all/{user_id}", tokens=("write",)
            )
        except AdapterError as exc:
            if exc.diagnostic is not None and exc.diagnostic.code == "not_found":
                raise PermissionMissing("gitlab", "write") from None  # parent ou membre inconnu
            raise
        level = _obj(data).get("access_level")
        if type(level) is not int or level < OWNER:
            raise PermissionMissing("gitlab", "write")

    async def _find(self, kind: str, full_path: str) -> Obj | None:
        try:
            data, _ = await self._client.get(
                f"/{kind}/{quote(full_path, safe='')}", tokens=("write",)
            )
        except AdapterError as exc:
            if exc.diagnostic is not None and exc.diagnostic.code == "not_found":
                return None
            raise
        return _obj(data)

    async def _create(self, params: Mapping[str, JsonValue], *, group: bool) -> AdapterResult:
        parent_id = _int(params, "parent_group_id")
        name, path = params.get("name"), params.get("path")
        pattern = _GROUP_PATH if group else _PROJECT_PATH
        if not isinstance(name, str) or not name or len(name) > 64:
            raise AdapterError("paramètre invalide")
        if not isinstance(path, str) or not pattern.fullmatch(path):
            raise AdapterError("paramètre invalide")
        boilerplate = params.get("boilerplate")
        if not group and boilerplate not in ("go-api", "vue-web"):
            raise AdapterError("paramètre invalide")
        async with self._write_lock:
            await self._owner_check(parent_id)
            parent_raw, _ = await self._client.get(f"/groups/{parent_id}", tokens=("write",))
            parent_path = _obj(parent_raw).get("full_path")
            if not isinstance(parent_path, str) or not parent_path:
                raise gitlab_error("bad_response")
            existing = await self._find("groups" if group else "projects", f"{parent_path}/{path}")
            created = existing is None
            if existing is not None:
                description = existing.get("description")
                if not isinstance(description, str) or MARKING not in description:
                    raise ForeignResource("ressource existante non gérée par Foreman")
                item = existing
            elif group:
                body: dict[str, JsonValue] = {
                    "parent_id": parent_id,
                    "name": name,
                    "path": path,
                    "visibility": "private",
                    "description": f"Groupe créé par Foreman ({MARKING})",
                }
                item = _obj(await self._client.post("/groups", body))
            else:
                # PoC : dépôt vide + README ; import du boilerplate : décision n°2 (ROADMAP).
                body = {
                    "namespace_id": parent_id,
                    "name": name,
                    "path": path,
                    "visibility": "private",
                    "initialize_with_readme": True,
                    "description": f"Dépôt Foreman ({MARKING}) ; boilerplate {boilerplate}",
                }
                item = _obj(await self._client.post("/projects", body))
        item_id, url = item.get("id"), item.get("web_url")
        if type(item_id) is not int or not isinstance(url, str):
            raise gitlab_error("bad_response")
        output: dict[str, JsonValue] = {
            ("group_id" if group else "project_id"): item_id,
            "web_url": url,
        }
        verb = "créé" if created else "déjà présent"
        return AdapterResult(
            output=output, logs=[f"{'groupe' if group else 'dépôt'} {path} {verb}"], created=created
        )

    async def _collection(
        self,
        path: str,
        params: Mapping[str, JsonValue],
        key: str,
        fields: tuple[str, ...],
        extra: Mapping[str, str | int] | None = None,
    ) -> AdapterResult:
        data, next_page = await self._client.get(path, {**_page(params), **(extra or {})})
        return self._wrap(key, [_pick(i, fields) for i in _list(data)], next_page)

    async def _project_list(
        self,
        params: Mapping[str, JsonValue],
        suffix: str,
        key: str,
        shape: Callable[[Obj], dict[str, JsonValue]],
        extra: Mapping[str, str | int] | None = None,
    ) -> AdapterResult:
        path = f"/projects/{_int(params, 'project_id')}/{suffix}"
        data, next_page = await self._client.get(path, {**_page(params), **(extra or {})})
        return self._wrap(key, [shape(i) for i in _list(data)], next_page)

    @staticmethod
    def _wrap(key: str, items: list[dict[str, JsonValue]], next_page: int | None) -> AdapterResult:
        # shortcut: filet de sécurité, les derniers éléments sont écartés (sans le dire) si la
        # page dépasse le budget ; à revoir si le schéma de sortie gagne un indicateur.
        while len(items) > 1 and len(json.dumps(items)) > MAX_LIST_BYTES:
            items = items[:-1]
        output: dict[str, JsonValue] = {key: list(items)}
        if next_page is not None:  # absent en dernière page, comme dans le faux
            output["next_page"] = next_page
        return AdapterResult(output=output)

    async def _read_file(self, params: Mapping[str, JsonValue]) -> AdapterResult:
        project_id = _int(params, "project_id")
        path = params.get("path")
        if not isinstance(path, str) or not path or len(path) > 500 or "\x00" in path:
            raise AdapterError("paramètre invalide")
        if _forbidden(path):
            raise AdapterError("fichier non lisible")
        ref = params.get("ref")
        if ref is None:
            project, _ = await self._client.get(f"/projects/{project_id}")
            ref = _obj(project).get("default_branch")
        if not isinstance(ref, str) or not ref:
            raise AdapterError("paramètre invalide")
        data, _ = await self._client.get(
            f"/projects/{project_id}/repository/files/{quote(path, safe='')}", {"ref": ref}
        )
        item = _obj(data)
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size > MAX_FILE_BYTES:
            raise AdapterError("fichier trop volumineux")
        encoded = item.get("content")
        if item.get("encoding") != "base64" or not isinstance(encoded, str):
            raise gitlab_error("bad_response")
        try:
            raw = base64.b64decode(encoded, validate=False)
            if len(raw) > MAX_FILE_BYTES or b"\x00" in raw:
                raise ValueError
            text = raw.decode("utf-8")
        except (binascii.Error, ValueError):
            raise AdapterError("fichier binaire ou trop volumineux") from None
        # Pas de masquage ligne à ligne ici : il effacerait le marqueur `BEGIN ... PRIVATE KEY`
        # dont la gateway a besoin pour masquer le corps de la clé. La gateway masque la chaîne.
        return AdapterResult(
            output={
                "path": path,
                "ref": ref,
                "size": size,
                "content": text[:MAX_CONTENT_CHARS],
                "truncated": len(text) > MAX_CONTENT_CHARS,
            }
        )

    async def probe(self, token: str, name: str, call: str) -> ProbeOutcome:
        """Scopes lus sur `personal_access_tokens/self`, puis l'appel déclaré (GET seul)."""
        tokens = (token,)
        try:
            raw, _ = await self._client.get("/personal_access_tokens/self", tokens=tokens)
        except PermissionMissing:
            return ProbeOutcome(ok=False)
        me = _obj(raw)
        scopes = me.get("scopes")
        found = (
            frozenset(s for s in scopes if isinstance(s, str))
            if isinstance(scopes, list)
            else frozenset()
        )
        target = _PLACEHOLDER.sub(str(me.get("user_id")), call.removeprefix("GET "))
        if not call.startswith("GET ") or "None" in target:
            raise gitlab_error("unsupported")
        if target == _PAT_SELF:  # sonde de validité du jeton : déjà lu, rien d'autre à appeler
            usable = me.get("active") is True and "api" in found and me.get("revoked") is not True
            return ProbeOutcome(ok=True, scopes=found, observed={"usable": int(usable)})
        url = urlsplit(target)
        try:
            data, _ = await self._client.get(url.path, dict(parse_qsl(url.query)), tokens=tokens)
        except PermissionMissing:
            return ProbeOutcome(ok=False, scopes=found)
        except AdapterError as exc:
            if exc.diagnostic is not None and exc.diagnostic.code == "not_found":
                return ProbeOutcome(ok=False, scopes=found)  # pas membre du groupe
            raise
        level = data.get("access_level") if isinstance(data, dict) else None
        observed = {"access_level": level} if type(level) is int else None
        return ProbeOutcome(ok=True, scopes=found, observed=observed)
