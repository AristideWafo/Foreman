"""Faux GitLab déterministe : « lecture puis création », état inspectable par les tests."""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

from pydantic import JsonValue

from foreman.core.ports import AdapterError, AdapterResult, ForeignResource, ProbeOutcome

BASE_URL = "https://gitlab.example.org"
ROOT_GROUP_ID = 1000
ROOT_GROUP_PATH = "foreman-demo"
FOREIGN_GROUP_ID = 1500
FOREIGN_PROJECT_ID = 4500
FIRST_GROUP_ID = 2000
FIRST_PROJECT_ID = 5000
MARKING = "managed-by=foreman"


@dataclass(frozen=True, slots=True)
class SimulatedGroup:
    id: int
    parent_id: int
    name: str
    path: str
    full_path: str
    web_url: str
    description: str


@dataclass(frozen=True, slots=True)
class SimulatedProject:
    id: int
    group_id: int
    name: str
    path: str
    boilerplate: str
    web_url: str
    description: str


def _int(params: Mapping[str, JsonValue], key: str) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError("paramètre invalide")
    return value


def _str(params: Mapping[str, JsonValue], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise AdapterError("paramètre invalide")
    return value


class SimulatedGitLab:
    """Les identifiants sont séquentiels (groupes dès 2000, dépôts dès 5000 par défaut) : un
    enregistrement de modèle peut donc viser le groupe créé par une étape précédente. Le registre
    de ressources survit aux redémarrages, pas ce faux : un serveur démarre donc à des bases
    aléatoires (`bootstrap/adapters.py`) pour ne jamais redonner un identifiant déjà inscrit.

    Deux ressources préexistantes, NON marquées `managed-by=foreman` (groupe `legacy`, dépôt
    `legacy-api`), sont semées au départ : « lire puis créer » ne doit jamais adopter ce que
    Foreman n'a pas créé, le fake lève `ForeignResource`.

    La lecture et la création partagent une même section critique (`_lock`) : deux appels
    concurrents pour le même groupe ne créent qu'une ressource. Le `await sleep(0)` entre les deux
    rend la course réelle si le verrou disparaît.
    """

    def __init__(
        self,
        root_group_id: int = ROOT_GROUP_ID,
        root_group_path: str = ROOT_GROUP_PATH,
        *,
        seed_foreign: bool = True,
        first_group_id: int = FIRST_GROUP_ID,
        first_project_id: int = FIRST_PROJECT_ID,
    ) -> None:
        self.epoch = uuid4().hex[:8]  # état en mémoire : voir `ToolAdapter` (époque d'adaptateur)
        self._root_id = root_group_id
        self._root_path = root_group_path
        self.groups: dict[int, SimulatedGroup] = {}
        self.projects: dict[int, SimulatedProject] = {}
        if seed_foreign:
            self._seed_foreign()
        self._lock = asyncio.Lock()
        self._next_group_id = first_group_id
        self._next_project_id = first_project_id

    @classmethod
    def from_referentiel(
        cls,
        gitlab_groups: Mapping[str, JsonValue],
        *,
        first_group_id: int = FIRST_GROUP_ID,
        first_project_id: int = FIRST_PROJECT_ID,
    ) -> "SimulatedGitLab":
        """Construit le faux depuis le référentiel `gitlab-groups` (groupe racine)."""
        root = gitlab_groups.get("root_group")
        if not isinstance(root, dict):
            raise AdapterError("référentiel GitLab invalide")
        root_id, root_path = root.get("id"), root.get("path")
        if (
            isinstance(root_id, bool)
            or not isinstance(root_id, int)
            or not isinstance(root_path, str)
        ):
            raise AdapterError("référentiel GitLab invalide")
        return cls(
            root_id,
            root_path,
            first_group_id=first_group_id,
            first_project_id=first_project_id,
        )

    def _seed_foreign(self) -> None:
        """Ressources préexistantes que Foreman n'a PAS créées (sans marquage `managed-by`)."""
        full_path = f"{self._root_path}/legacy"
        self.groups[FOREIGN_GROUP_ID] = SimulatedGroup(
            id=FOREIGN_GROUP_ID,
            parent_id=self._root_id,
            name="Legacy",
            path="legacy",
            full_path=full_path,
            web_url=f"{BASE_URL}/{full_path}",
            description="Groupe historique de l'équipe",
        )
        self.projects[FOREIGN_PROJECT_ID] = SimulatedProject(
            id=FOREIGN_PROJECT_ID,
            group_id=FOREIGN_GROUP_ID,
            name="legacy-api",
            path="legacy-api",
            boilerplate="go-api",
            web_url=f"{BASE_URL}/{full_path}/legacy-api",
            description="Dépôt historique",
        )

    async def probe(self, token: str, name: str, call: str) -> ProbeOutcome:
        """Faux : tous les droits déclarés sont présents (et seulement eux), aucun état touché."""
        scopes = {"read": frozenset({"read_api"}), "write": frozenset({"api"})}.get(token)
        return ProbeOutcome(ok=True, scopes=scopes or frozenset(), observed={"usable": 1})

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        # La clé n'est pas stockée : l'idempotence est celle de l'outil (lecture puis création).
        if tool == "gitlab.create_group":
            return await self._create_group(params)
        if tool == "gitlab.create_project":
            return await self._create_project(params)
        reader = self._READS.get(tool)
        if reader is not None:
            return AdapterResult(output=reader(self, params), logs=[])
        raise AdapterError("outil non fourni par ce connecteur")

    # --- Lectures (chat) : listes courtes et déterministes, sans état modifié ------------------

    def _project(self, params: Mapping[str, JsonValue]) -> SimulatedProject:
        project = self.projects.get(_int(params, "project_id"))
        if project is None:
            raise AdapterError("projet introuvable")
        return project

    def _list_groups(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        parent = params.get("parent_group_id", self._root_id)
        search = str(params.get("search", "")).lower()
        found: list[JsonValue] = [
            {"id": g.id, "name": g.name, "full_path": g.full_path, "web_url": g.web_url}
            for g in self.groups.values()
            if g.parent_id == parent and search in g.name.lower()
        ]
        return {"groups": found}

    def _list_projects(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        group_id, search = _int(params, "group_id"), str(params.get("search", "")).lower()
        group = self.groups.get(group_id)
        found: list[JsonValue] = [
            self._project_summary(p, group.full_path)
            for p in self.projects.values()
            if group is not None and p.group_id == group_id and search in p.name.lower()
        ]
        return {"projects": found}

    def _project_summary(self, project: SimulatedProject, group_path: str) -> dict[str, JsonValue]:
        return {
            "id": project.id,
            "name": project.name,
            "path_with_namespace": f"{group_path}/{project.path}",
            "web_url": project.web_url,
            "default_branch": "main",
            "last_activity_at": "2026-01-01T00:00:00Z",
        }

    def _get_project(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        project = self._project(params)
        summary = self._project_summary(project, self.groups[project.group_id].full_path)
        return {
            **{k: summary[k] for k in ("id", "name", "path_with_namespace", "web_url")},
            "default_branch": "main",
            "visibility": "private",
            "description": project.description[:300],
            "open_issues_count": 2,
        }

    def _list_branches(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        self._project(params)
        search = str(params.get("search", "")).lower()
        branches = [("main", True, True, "a1b2c3d"), ("feat/demo", False, False, "d4e5f6a")]
        return {
            "branches": [
                {"name": n, "default": d, "protected": pr, "commit_short_id": c}
                for n, d, pr, c in branches
                if search in n
            ]
        }

    def _list_pipelines(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        project = self._project(params)
        rows = [(9001, "success", "main"), (9002, "failed", "feat/demo")]
        return {
            "pipelines": [
                {
                    "id": i,
                    "status": st,
                    "ref": ref,
                    "web_url": f"{project.web_url}/-/pipelines/{i}",
                    "created_at": "2026-01-01T00:00:00Z",
                }
                for i, st, ref in rows
                if params.get("ref", ref) == ref and params.get("status", st) == st
            ]
        }

    def _list_issues(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        project = self._project(params)
        state, search = params["state"], str(params.get("search", "")).lower()
        rows = [(1, "Ajouter l'authentification", "opened"), (2, "Corriger le logo", "closed")]
        return {
            "issues": [
                {
                    "iid": i,
                    "title": t,
                    "state": st,
                    "author": "demo",
                    "labels": ["demo"],
                    "web_url": f"{project.web_url}/-/issues/{i}",
                }
                for i, t, st in rows
                if state in ("all", st) and search in t.lower()
            ]
        }

    def _list_merge_requests(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        project = self._project(params)
        state = params["state"]
        rows = [
            (1, "Ajouter la page d'accueil", "opened"),
            (2, "Mettre à jour le README", "merged"),
        ]
        return {
            "merge_requests": [
                {
                    "iid": i,
                    "title": t,
                    "state": st,
                    "source_branch": "feat/demo",
                    "target_branch": "main",
                    "author": "demo",
                    "web_url": f"{project.web_url}/-/merge_requests/{i}",
                }
                for i, t, st in rows
                if state in ("all", st)
            ]
        }

    def _read_file(self, params: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        project = self._project(params)
        path = _str(params, "path")
        if path != "README.md":
            raise AdapterError("fichier introuvable")
        content = f"# {project.name}\n\n{project.description}\n"
        return {
            "path": path,
            "ref": str(params.get("ref", "main")),
            "size": len(content),
            "content": content[:3000],
            "truncated": False,
        }

    _READS: ClassVar[
        dict[str, Callable[["SimulatedGitLab", Mapping[str, JsonValue]], dict[str, JsonValue]]]
    ] = {
        "gitlab.list_groups": _list_groups,
        "gitlab.list_projects": _list_projects,
        "gitlab.get_project": _get_project,
        "gitlab.list_branches": _list_branches,
        "gitlab.list_pipelines": _list_pipelines,
        "gitlab.list_issues": _list_issues,
        "gitlab.list_merge_requests": _list_merge_requests,
        "gitlab.read_file": _read_file,
    }

    def _parent_path(self, parent_id: int) -> str:
        if parent_id == self._root_id:
            return self._root_path
        parent = self.groups.get(parent_id)
        if parent is None:
            raise AdapterError("groupe parent introuvable")
        return parent.full_path

    async def _create_group(self, params: Mapping[str, JsonValue]) -> AdapterResult:
        parent_id, name, path = (
            _int(params, "parent_group_id"),
            _str(params, "name"),
            _str(params, "path"),
        )
        async with self._lock:
            parent_path = self._parent_path(parent_id)
            existing = next(
                (g for g in self.groups.values() if g.parent_id == parent_id and g.path == path),
                None,
            )
            await asyncio.sleep(0)  # point de suspension : la course serait réelle sans verrou
            if existing is not None:
                if MARKING not in existing.description:
                    raise ForeignResource("groupe existant non géré par Foreman")
                return self._group_result(existing, created=False)
            full_path = f"{parent_path}/{path}"
            group = SimulatedGroup(
                id=self._next_group_id,
                parent_id=parent_id,
                name=name,
                path=path,
                full_path=full_path,
                web_url=f"{BASE_URL}/{full_path}",
                description=f"Groupe créé par Foreman ({MARKING})",
            )
            self._next_group_id += 1
            self.groups[group.id] = group
            return self._group_result(group, created=True)

    @staticmethod
    def _group_result(group: SimulatedGroup, *, created: bool) -> AdapterResult:
        verb = "créé" if created else "déjà présent"
        return AdapterResult(
            output={"group_id": group.id, "web_url": group.web_url},
            logs=[f"groupe {group.full_path} {verb}"],
            created=created,
        )

    async def _create_project(self, params: Mapping[str, JsonValue]) -> AdapterResult:
        group_id, name, path = (
            _int(params, "parent_group_id"),
            _str(params, "name"),
            _str(params, "path"),
        )
        boilerplate = _str(params, "boilerplate")
        async with self._lock:
            group = self.groups.get(group_id)
            if group is None:
                raise AdapterError("groupe parent introuvable")
            existing = next(
                (p for p in self.projects.values() if p.group_id == group_id and p.path == path),
                None,
            )
            await asyncio.sleep(0)  # point de suspension : la course serait réelle sans verrou
            if existing is not None:
                if MARKING not in existing.description:
                    raise ForeignResource("dépôt existant non géré par Foreman")
                return self._project_result(existing, created=False)
            project = SimulatedProject(
                id=self._next_project_id,
                group_id=group_id,
                name=name,
                path=path,
                boilerplate=boilerplate,
                web_url=f"{BASE_URL}/{group.full_path}/{path}",
                description=f"Dépôt créé par Foreman ({MARKING})",
            )
            self._next_project_id += 1
            self.projects[project.id] = project
            return self._project_result(project, created=True)

    @staticmethod
    def _project_result(project: SimulatedProject, *, created: bool) -> AdapterResult:
        verb = "créé" if created else "déjà présent"
        return AdapterResult(
            output={"project_id": project.id, "web_url": project.web_url},
            logs=[f"dépôt {project.path} {verb} (boilerplate {project.boilerplate})"],
            created=created,
        )
