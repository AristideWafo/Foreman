"""Aides communes aux tests : un planificateur réel sur le catalogue du dépôt et la mémoire."""

from foreman.core.planning import Planner
from foreman.core.ports import ConversationMessage
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import in_memory_stores


def make_planner() -> Planner:
    """À appeler dans un test (le dossier du catalogue vient de la fixture `catalog_dir_env`)."""
    catalog = load_catalog(environment="staging")
    return Planner(catalog, in_memory_stores()[1].plans)


def user(*texts: str) -> list[ConversationMessage]:
    """Un historique de messages utilisateur (le dernier est celui du tour)."""
    return [ConversationMessage("user", text) for text in texts]
