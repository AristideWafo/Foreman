"""Aides communes aux tests : un planificateur réel sur le catalogue du dépôt et la mémoire."""

from foreman.core.identity import Member, Principal
from foreman.core.planning import Planner
from foreman.core.ports import ConversationMessage
from foreman.core.store import DEV_USER_ID
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryMemberStore, in_memory_stores


def make_planner() -> Planner:
    """À appeler dans un test (le dossier du catalogue vient de la fixture `catalog_dir_env`)."""
    catalog = load_catalog(environment="staging")
    return Planner(catalog, (s := in_memory_stores()[1]).plans, s.registry)


def user(*texts: str) -> list[ConversationMessage]:
    """Un historique de messages utilisateur (le dernier est celui du tour)."""
    return [ConversationMessage("user", text) for text in texts]


DEV_PRINCIPAL = Principal(user_id=DEV_USER_ID, name="dev", role="developer")

# Seuls team_admin et org_admin valident un plan (#248) : les tests valident avec cet admin.
# Limite : `dev_members()` garde `dev` développeur ; ce principal ne sert qu'aux appels de service.
ADMIN_PRINCIPAL = Principal(user_id=DEV_USER_ID, name="dev", role="team_admin")


def dev_members() -> InMemoryMemberStore:
    """Droits du mode `none` : `dev` est développeur (la gateway relit ce rôle)."""
    return InMemoryMemberStore([Member("dev", "developer", DEV_USER_ID)])
