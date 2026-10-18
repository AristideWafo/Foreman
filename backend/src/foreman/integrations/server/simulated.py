"""Faux serveur déterministe : playbooks `bootstrap_project` et `deploy_compose`, health check."""

import asyncio
import copy
from collections.abc import Mapping
from dataclasses import dataclass, field

from pydantic import JsonValue

from foreman.core.ports import AdapterError, AdapterResult

PLAYBOOKS = ("bootstrap_project", "deploy_compose")
_TASKS = {
    "bootstrap_project": [
        "Créer le répertoire du projet",
        "Installer le fichier Compose",
        "Créer le réseau du projet",
    ],
    "deploy_compose": [
        "Tirer les images",
        "Démarrer les services Compose",
        "Déclarer le sous-domaine dans Caddy",
    ],
}

ProjectKey = tuple[str, str]  # (environnement, slug du projet)


@dataclass(slots=True)
class SimulatedServerProject:
    environment: str
    bootstrapped: bool = False
    deployed: bool = False
    runs: list[str] = field(default_factory=list)


def _str(params: Mapping[str, JsonValue], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise AdapterError("paramètre invalide")
    return value


class SimulatedServer:
    """`apply_playbook` rejoue le résultat précédent pour une même clé (`return_previous_result`),
    sans nouvelle exécution. L'état est indexé par (environnement, projet) et inspectable
    (`.projects`, `.runs`).

    La clé d'idempotence identifie un appel précis : la gateway garantit qu'une même clé n'est
    utilisée que pour l'appel identique de l'étape du plan, le fake ne compare donc pas les
    paramètres. Les résultats sont copiés au stockage et au retour : un appelant ne peut pas
    altérer le cache. Le compteur de `run_id` avance à chaque exécution, quel que soit le mode.
    """

    def __init__(self) -> None:
        self.projects: dict[ProjectKey, SimulatedServerProject] = {}
        self.runs: list[str] = []  # exécutions en mode apply, dans l'ordre
        self._results: dict[str, AdapterResult] = {}
        self._run_counter = 0
        self._lock = asyncio.Lock()

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        if tool == "server.apply_playbook":
            return await self._apply_playbook(params, idempotency_key)
        if tool == "server.healthcheck":
            return self._healthcheck(params)
        raise AdapterError("outil non fourni par ce connecteur")

    async def _apply_playbook(
        self, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        environment = _str(params, "environment")
        project = _str(params, "project")
        playbook = _str(params, "playbook")
        mode = _str(params, "mode")
        if playbook not in PLAYBOOKS or mode not in ("check", "apply"):
            raise AdapterError("playbook ou mode inconnu")
        key: ProjectKey = (environment, project)
        async with self._lock:
            previous = self._results.get(idempotency_key)
            if previous is not None:
                return copy.deepcopy(previous)
            await asyncio.sleep(0)  # point de suspension : la course serait réelle sans verrou
            state = self.projects.get(key)
            if playbook == "deploy_compose" and (state is None or not state.bootstrapped):
                raise AdapterError("projet non préparé")
            already_done = state is not None and (
                state.bootstrapped if playbook == "bootstrap_project" else state.deployed
            )
            self._run_counter += 1
            run_id = f"run-{self._run_counter:04d}"
            tasks = [] if already_done else list(_TASKS[playbook])
            verb = "ok" if already_done else "changed"
            logs = [f"PLAY [{playbook}] projet={project} mode={mode}"]
            logs += [f"{verb}: {t}" for t in _TASKS[playbook]]
            if mode == "apply":
                state = self.projects.setdefault(key, SimulatedServerProject(environment))
                if playbook == "bootstrap_project":
                    state.bootstrapped = True
                else:
                    state.deployed = True
                state.runs.append(run_id)
                self.runs.append(run_id)
            result = AdapterResult(
                output={
                    "run_id": run_id,
                    "status": "ok" if already_done else "changed",
                    "changed_tasks": list(tasks),
                },
                logs=logs,
            )
            if mode == "apply":
                self._results[idempotency_key] = copy.deepcopy(result)
            return result

    def _healthcheck(self, params: Mapping[str, JsonValue]) -> AdapterResult:
        state = self.projects.get((_str(params, "environment"), _str(params, "project")))
        if state is not None and state.deployed:
            output: dict[str, JsonValue] = {"status": "ok", "http_status": 200, "database": "ok"}
        else:
            output = {"status": "failed", "http_status": 503, "database": "unreachable"}
        return AdapterResult(output=output, logs=[f"healthcheck : {output['status']}"])
