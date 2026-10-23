"""`RealGitLab` : lectures (REST gitlab.com) et sondeur. Écritures : plus tard.

Sorties en LISTE D'AUTORISATION de champs : tout ce que GitLab renvoie en plus (runners_token,
variables, ...) est ignoré. Pagination imposée : `per_page=20`, `page` de 1 à 10.
"""

import base64
import binascii
import fnmatch
import re
from collections.abc import Callable, Mapping
from typing import Final
from urllib.parse import parse_qsl, quote, urlsplit

from pydantic import JsonValue

from foreman.core.gateway.redact import mask_text
from foreman.core.ports import AdapterError, AdapterResult, PermissionMissing, ProbeOutcome
from foreman.integrations.gitlab.client import GitLabClient, gitlab_error

PER_PAGE: Final = 20
MAX_PAGE: Final = 10
MAX_FILE_BYTES: Final = 64 * 1024
MAX_CONTENT_CHARS: Final = 3000
_FORBIDDEN_FILES: Final = (".env", ".env.*", "*.pem", "*.key", "id_rsa*")
_STATES: Final = ("opened", "closed", "merged", "all")
_PLACEHOLDER: Final = re.compile(r"\{(root_id|user_id)\}")

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
    return _text(author.get("username"), 100) if isinstance(author, dict) else ""


def _labels(item: Obj) -> list[JsonValue]:
    labels = item.get("labels")
    return [_text(x, 50) for x in labels[:20]] if isinstance(labels, list) else []


def _issue(item: Obj) -> dict[str, JsonValue]:
    return {
        "iid": item.get("iid"),
        "title": _text(item.get("title"), 200),
        "state": item.get("state"),
        "author": _author(item),
        "labels": _labels(item),
        "web_url": item.get("web_url"),
    }


def _mr(item: Obj) -> dict[str, JsonValue]:
    return {
        **_pick(item, ("iid",)),
        "title": _text(item.get("title"), 200),
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

    def __init__(self, client: GitLabClient, root_group_id: int) -> None:
        self._client = client
        self._root_id = root_group_id

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        # Lectures seules : idempotentes par nature, la clé est inutile.
        match tool:
            case "gitlab.list_groups":
                return await self._collection(
                    "/groups",
                    params,
                    "groups",
                    ("id", "name", "full_path", "web_url"),
                    {"min_access_level": 10},
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
                if "group_id" in params:
                    path = f"/groups/{_int(params, 'group_id')}/projects"
                    return await self._collection(path, params, "projects", fields)
                return await self._collection(
                    "/projects", params, "projects", fields, {"membership": "true"}
                )
            case "gitlab.get_project":
                data, _ = await self._client.get(f"/projects/{_int(params, 'project_id')}")
                return AdapterResult(output=_project_detail(_obj(data)))
            case "gitlab.list_branches":
                return await self._project_list(params, "repository/branches", "branches", _branch)
            case "gitlab.list_pipelines":
                return await self._project_list(params, "pipelines", "pipelines", _pipeline)
            case "gitlab.list_issues":
                return await self._project_list(
                    params, "issues", "issues", _issue, self._state(params)
                )
            case "gitlab.list_merge_requests":
                return await self._project_list(
                    params, "merge_requests", "merge_requests", _mr, self._state(params)
                )
            case "gitlab.read_file":
                return await self._read_file(params)
        raise gitlab_error("unsupported")

    @staticmethod
    def _state(params: Mapping[str, JsonValue]) -> dict[str, str | int]:
        state = params.get("state")
        if state is None:
            return {}
        if state not in _STATES:
            raise AdapterError("paramètre invalide")
        return {"state": str(state)}

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
        return AdapterResult(output={key: list(items), "next_page": next_page})

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
        # mask_text borne ses entrées (2000 car.) : on masque ligne par ligne, puis on coupe.
        masked = "\n".join(mask_text(line) for line in text.splitlines())
        return AdapterResult(
            output={
                "path": path,
                "ref": ref,
                "size": size,
                "content": masked[:MAX_CONTENT_CHARS],
                "truncated": len(text)
                > MAX_CONTENT_CHARS,  # mask_text coupe aussi les longues lignes
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
        values = {"root_id": self._root_id, "user_id": me.get("user_id")}
        target = _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), call.removeprefix("GET "))
        if not call.startswith("GET ") or "None" in target:
            raise gitlab_error("unsupported")
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
