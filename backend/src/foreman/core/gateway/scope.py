"""Périmètre d'un appel : où l'outil a le droit d'agir.

- création : le parent est une racine déclarée par un référentiel, ou une ressource du registre
  DU PROJET ; exception GitLab : tout groupe (entier > 0), l'adaptateur vérifiant le rôle Owner ;
- mise à jour : la cible est une ressource du registre du projet (de la même famille que l'outil) ;
- lecture : pas de contrainte de registre.

Fermé par défaut : un couple (connecteur, paramètre parent) absent de `PARENTS` est refusé. Un
nouvel outil de création doit donc déclarer ici d'où vient son parent.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import JsonValue

from foreman.core.catalog import Catalog, ToolDefinition
from foreman.core.store import ResourceRegistry


def _environment_roots(catalog: Catalog) -> frozenset[str]:
    ref = catalog.referentiels.get("environments")
    environments = ref.data.get("environments") if ref is not None else None
    return frozenset(environments) if isinstance(environments, dict) else frozenset()


def _no_roots(catalog: Catalog) -> frozenset[str]:
    return frozenset()


@dataclass(frozen=True, slots=True)
class ParentKind:
    resource_type: str | None  # famille de registre des parents ; None : seules les racines
    roots: Callable[[Catalog], frozenset[str]]
    any_id: bool = False  # tout entier > 0 ; le droit est contrôlé par l'adaptateur


# (connecteur, paramètre parent) -> d'où vient le parent
PARENTS: Final[Mapping[tuple[str, str], ParentKind]] = {
    # Décision propriétaire : plus de racine fixe ; l'adaptateur exige Owner du parent à l'appel.
    ("gitlab", "parent_group_id"): ParentKind("gitlab_group", _no_roots, any_id=True),
    ("server", "environment"): ParentKind(None, _environment_roots),
}


def _identifier(value: JsonValue | None) -> str | None:
    """Forme textuelle d'un identifiant de ressource (entier ou chaîne), sinon `None`."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        return None
    text = str(value)
    return text or None


async def _owned_by_another_project(
    registry: ResourceRegistry,
    project_id: UUID,
    tool: ToolDefinition,
    params: Mapping[str, JsonValue],
) -> bool:
    """Vrai si la ressource à créer (son identifiant est un paramètre) est celle d'un autre projet.

    Un identifiant lu en SORTIE (GitLab) ne peut être contrôlé qu'après l'exécution : la gateway le
    fait alors (`foreign_resource`).
    """
    if tool.registry is None or (
        "{" not in tool.registry.external_id and (tool.registry.external_id not in params)
    ):
        return False
    external_id = _identifier(tool.registry.identify(params))
    if external_id is None:
        return True  # identifiant inutilisable : refusé
    return await registry.exists_elsewhere(
        project_id, tool.connector, tool.registry.resource_type, external_id
    )


async def in_scope(
    *,
    catalog: Catalog,
    registry: ResourceRegistry,
    project_id: UUID,
    tool: ToolDefinition,
    params: Mapping[str, JsonValue],
) -> bool:
    """Vrai si l'appel reste dans le périmètre du projet (registre cloisonné par `project_id`)."""
    scope = tool.effective_scope(params)
    if scope.kind == "read":
        return True
    if scope.kind == "create":
        kind = PARENTS.get((tool.connector, scope.parent or ""))
        parent = _identifier(params.get(scope.parent or ""))
        if kind is None or parent is None:
            return False
        if kind.any_id:
            if not (parent.isdigit() and int(parent) > 0):
                return False
            return not await _owned_by_another_project(registry, project_id, tool, params)
        in_roots = parent in kind.roots(catalog)
        if not in_roots and not (
            kind.resource_type is not None
            and await registry.contains(project_id, tool.connector, kind.resource_type, parent)
        ):
            return False
        return not await _owned_by_another_project(registry, project_id, tool, params)
    if tool.registry is None:
        return False
    # Le projet visé est identifié comme à son enregistrement (gabarit environnement/slug).
    target = _identifier(tool.registry.identify(params)) if scope.target else None
    if target is None:
        return False
    return await registry.contains(project_id, tool.connector, tool.registry.resource_type, target)
