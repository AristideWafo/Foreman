"""Adaptateurs de connecteurs et assemblage de la gateway.

Seul endroit où `integrations` est importé : le cœur et le moteur ne connaissent que le port
`ToolAdapter`, et n'atteignent un adaptateur que par la `Gateway`. Cette semaine, ce sont les
faux (serveur, DNS) ; GitLab bascule sur le vrai dès qu'un jeton est saisi (`ConfiguredGitLab`).
"""

import os
import secrets
from collections.abc import Mapping

from pydantic import JsonValue

from foreman.core.catalog import Catalog
from foreman.core.connector_state import ConnectorStore, connector_secret_id
from foreman.core.gateway.pipeline import ToolGateway
from foreman.core.ports import (
    AdapterError,
    AdapterResult,
    ConnectorProber,
    MemberStore,
    PermissionMissing,
    ProbeOutcome,
    ToolAdapter,
)
from foreman.core.secrets import SecretStore
from foreman.core.store import Stores
from foreman.integrations.dns.simulated import SimulatedDns
from foreman.integrations.gitlab.adapter import RealGitLab
from foreman.integrations.gitlab.client import GitLabClient
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


WRITE_TOOLS = frozenset({"gitlab.create_group", "gitlab.create_project"})


class ConfiguredGitLab:
    """Relit à CHAQUE appel si un jeton GitLab existe (la page d'admin peut le changer en vol).

    Au moins un jeton : le vrai, pour les lectures ET les écritures (une écriture sans jeton
    d'écriture est refusée, jamais confiée au faux). Aucun jeton : le faux. Une erreur du vrai ne
    retombe jamais sur le faux.
    """

    def __init__(self, fake: SimulatedGitLab, real: RealGitLab, store: SecretStore) -> None:
        self._fake = fake
        self._real = real
        self._secrets = store
        self.epoch = fake.epoch

    async def _tokens(self) -> tuple[bool, bool]:
        read = await self._secrets.exists(connector_secret_id("gitlab", "read"))
        write = await self._secrets.exists(connector_secret_id("gitlab", "write"))
        return read, write

    async def execute(
        self, tool: str, params: Mapping[str, JsonValue], idempotency_key: str
    ) -> AdapterResult:
        read, write = await self._tokens()
        if not (read or write):
            return await self._fake.execute(tool, params, idempotency_key)
        if tool in WRITE_TOOLS and not write:
            raise PermissionMissing("gitlab", "write")
        return await self._real.execute(tool, params, idempotency_key)

    async def probe(self, token: str, name: str, call: str) -> ProbeOutcome:
        read, write = await self._tokens()
        if not (read or write):
            return await self._fake.probe(token, name, call)
        return await self._real.probe(token, name, call)  # jeton manquant : droit manquant


def _root_group_id(catalog: Catalog) -> int:
    root = catalog.referentiels["gitlab-groups"].data.get("root_group")
    root_id = root.get("id") if isinstance(root, dict) else None
    if isinstance(root_id, bool) or not isinstance(root_id, int):
        raise AdapterError("référentiel GitLab invalide")
    return root_id


def build_adapters(
    catalog: Catalog,
    store: SecretStore,
    *,
    durable_registry: bool = False,
    force_fake: bool = False,
) -> dict[str, ToolAdapter]:
    """Un adaptateur par connecteur, configuré depuis les référentiels du catalogue.

    `force_fake` (profil EVAL) et la variable `CI` imposent toujours le faux GitLab."""
    fake = SimulatedGitLab.from_referentiel(
        catalog.referentiels["gitlab-groups"].data,
        first_group_id=FIRST_GROUP_ID + (secrets.randbelow(ID_SPACE) if durable_registry else 0),
        first_project_id=FIRST_PROJECT_ID
        + (secrets.randbelow(ID_SPACE) if durable_registry else 0),
    )
    gitlab: ToolAdapter = fake
    if not (force_fake or os.environ.get("CI")):
        real = RealGitLab(GitLabClient(store), _root_group_id(catalog))
        gitlab = ConfiguredGitLab(fake, real, store)
    return {
        "gitlab": gitlab,
        "server": SimulatedServer(),
        "dns": SimulatedDns.from_referentiel(catalog.referentiels["infra-staging"].data),
    }


def build_gateway(
    catalog: Catalog,
    stores: Stores,
    members: MemberStore,
    store: SecretStore,
    *,
    durable_registry: bool = False,
    connector_store: ConnectorStore | None = None,
    force_fake: bool = False,
) -> ToolGateway:
    adapters = build_adapters(
        catalog, store, durable_registry=durable_registry, force_fake=force_fake
    )
    return ToolGateway(
        catalog=catalog,
        stores=stores,
        adapters=adapters,
        members=members,
        # Les faux sondent eux-mêmes (`probe`) ; un vrai connecteur fournira son propre sondeur.
        probers={name: a for name, a in adapters.items() if isinstance(a, ConnectorProber)},
        connector_store=connector_store,
    )
