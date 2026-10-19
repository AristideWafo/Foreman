"""Adaptateurs de connecteurs et assemblage de la gateway.

Seul endroit où `integrations` est importé : le cœur et le moteur ne connaissent que le port
`ToolAdapter`, et n'atteignent un adaptateur que par la `Gateway`. Cette semaine, ce sont les
faux (GitLab, serveur, DNS) ; les vrais connecteurs les remplaceront ici et nulle part ailleurs.
"""

from foreman.core.catalog import Catalog
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.ports import MemberStore, ToolAdapter
from foreman.core.store import Stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.simulated import SimulatedGitLab
from foreman.integrations.server.simulated import SimulatedServer


def build_adapters(catalog: Catalog) -> dict[str, ToolAdapter]:
    """Un adaptateur par connecteur, configuré depuis les référentiels du catalogue."""
    return {
        "gitlab": SimulatedGitLab.from_referentiel(catalog.referentiels["gitlab-groups"].data),
        "server": SimulatedServer(),
        "dns": SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data),
    }


def build_gateway(catalog: Catalog, stores: Stores, members: MemberStore) -> ToolGateway:
    return ToolGateway(
        catalog=catalog, stores=stores, adapters=build_adapters(catalog), members=members
    )
