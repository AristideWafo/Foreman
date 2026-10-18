"""Configuration du processus. L'ordre des étapes est fixe : un profil ne peut pas le changer."""

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum

from foreman.bootstrap.adapters import build_gateway
from foreman.bootstrap.database import DatabaseLifecycle, Lifecycle, NoLifecycle
from foreman.config.env import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_LEVEL,
    ENV_DATABASE_URL,
    ENV_ENVIRONMENT,
    ENV_LOG_LEVEL,
)
from foreman.core.approval import ApprovalService
from foreman.core.catalog import Catalog
from foreman.core.execution.engine import ExecutionEngine
from foreman.core.gateway.port import Gateway
from foreman.core.planning import Planner
from foreman.core.ports import EventLog, ProjectStore
from foreman.core.store import Stores
from foreman.core.turn import TurnService
from foreman.infra.db.engine import make_engine
from foreman.infra.db.projects import PostgresProjectStore
from foreman.infra.db.stores import postgres_stores
from foreman.infra.file_catalog import catalog_dir_from_env, load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores
from foreman.infra.replay_provider import ReplayProvider


class Profile(StrEnum):
    WEB = "web"
    CLI = "cli"
    WORKER = "worker"
    EVAL = "eval"


# Profils persistés en PostgreSQL quand l'URL est définie ; CLI et évaluations restent en mémoire.
_PERSISTENT_PROFILES = frozenset({Profile.WEB, Profile.WORKER})


def _memory_stores() -> Stores:
    return in_memory_stores()[1]


@dataclass(frozen=True, slots=True)
class App:
    profile: Profile
    projects: ProjectStore
    events: EventLog
    turns: TurnService
    stores: Stores = field(default_factory=_memory_stores)
    lifecycle: Lifecycle = field(default_factory=NoLifecycle)
    catalog: Catalog | None = None  # chargé par `configure` ; absent dans certains tests
    gateway: Gateway | None = None  # seul chemin vers les outils ; consommé par le moteur
    approvals: ApprovalService | None = None
    engine: ExecutionEngine | None = None
    persistence: str = "memory"  # « postgres » quand le stockage durable est branché


def configure(profile: Profile) -> App:
    # 1. Journalisation propre au processus
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    # 2. Catalogue : synchrone, avant la boucle asynchrone. Une erreur (fichier invalide, Skill
    #    brouillon hors staging, dossier absent) arrête le démarrage avec un message clair.
    environment = os.environ.get(ENV_ENVIRONMENT, DEFAULT_ENVIRONMENT)
    catalog = load_catalog(environment=environment)
    # 3. Adaptateurs de connecteurs : bootstrap/adapters.py (seul endroit qui importe integrations)
    provider = ReplayProvider.s01(catalog_dir_from_env())
    events = InMemoryEventLog()  # le chat reste en mémoire cette semaine
    projects: ProjectStore
    lifecycle: Lifecycle
    persistence = "memory"
    url = os.environ.get(ENV_DATABASE_URL)
    if url and profile in _PERSISTENT_PROFILES:
        engine = make_engine(url)  # ne se connecte pas : les migrations viennent au démarrage
        projects = PostgresProjectStore(engine)
        stores = postgres_stores(engine)
        lifecycle = DatabaseLifecycle(url, engine)
        persistence = "postgres"
    else:
        memory_projects = InMemoryProjectStore()
        projects = memory_projects
        stores = in_memory_stores(projects=memory_projects)[1]
        lifecycle = NoLifecycle()
    # 4. Services du cœur
    gateway = build_gateway(catalog, stores)
    return App(
        profile=profile,
        projects=projects,
        events=events,
        turns=TurnService(provider, events, Planner(catalog, stores.plans)),
        stores=stores,
        lifecycle=lifecycle,
        persistence=persistence,
        catalog=catalog,
        gateway=gateway,
        approvals=ApprovalService(catalog, stores, events),
        engine=ExecutionEngine(catalog=catalog, stores=stores, gateway=gateway, events=events),
    )
