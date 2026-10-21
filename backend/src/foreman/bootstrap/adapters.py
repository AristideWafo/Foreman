"""Adaptateurs de connecteurs et assemblage de la gateway.

Seul endroit où `integrations` est importé : le cœur et le moteur ne connaissent que le port
`ToolAdapter`, et n'atteignent un adaptateur que par la `Gateway`. Cette semaine, ce sont les
faux (GitLab, serveur, DNS) ; les vrais connecteurs les remplaceront ici et nulle part ailleurs.
"""

import secrets

from foreman.core.catalog import Catalog
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.ports import ConnectorProber, MemberStore, ToolAdapter
from foreman.core.store import Stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import (
    FIRST_GROUP_ID,
    FIRST_PROJECT_ID,
    SimulatedGitLab,
)
from foreman.integrations.server.simulated import SimulatedServer

# Registre durable (PostgreSQL) : il survit aux redémarrages, le faux GitLab non. Sans base
# aléatoire il redonnerait 2000 et 5000, déjà inscrits pour un autre projet (`foreign_resource`).
# En mémoire, les identifiants restent déterministes (scénarios rejoués, fixtures du front).
ID_SPACE = 2_000_000_000


def build_adapters(catalog: Catalog, *, durable_registry: bool = False) -> dict[str, ToolAdapter]:
    """Un adaptateur par connecteur, configuré depuis les référentiels du catalogue."""
    return {
        "gitlab": SimulatedGitLab.from_referentiel(
            catalog.referentiels["gitlab-groups"].data,
            first_group_id=FIRST_GROUP_ID
            + (secrets.randbelow(ID_SPACE) if durable_registry else 0),
            first_project_id=FIRST_PROJECT_ID
            + (secrets.randbelow(ID_SPACE) if durable_registry else 0),
        ),
        "server": SimulatedServer(),
        "dns": SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data),
    }


def build_gateway(
    catalog: Catalog, stores: Stores, members: MemberStore, *, durable_registry: bool = False
) -> ToolGateway:
    adapters = build_adapters(catalog, durable_registry=durable_registry)
    return ToolGateway(
        catalog=catalog,
        stores=stores,
        adapters=adapters,
        members=members,
        # Les faux sondent eux-mêmes (`probe`) ; un vrai connecteur fournira son propre sondeur.
        probers={name: a for name, a in adapters.items() if isinstance(a, ConnectorProber)},
    )
