"""Configuration du processus. L'ordre des étapes est fixe : un profil ne peut pas le changer."""

import logging
import os
from dataclasses import dataclass, field
from enum import StrEnum

from foreman.bootstrap.database import DatabaseLifecycle, Lifecycle, NoLifecycle
from foreman.config.env import DEFAULT_LOG_LEVEL, ENV_DATABASE_URL, ENV_LOG_LEVEL
from foreman.core.ports import EventLog, ProjectStore
from foreman.core.store import Stores
from foreman.core.turn import TurnService
from foreman.infra.db.engine import make_engine
from foreman.infra.db.projects import PostgresProjectStore
from foreman.infra.db.stores import postgres_stores
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore, in_memory_stores
from foreman.infra.scripted_provider import ScriptedProvider


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


def configure(profile: Profile) -> App:
    # 1. Journalisation propre au processus
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    # 2. Adaptateurs (un seul endroit : voir adapters.py quand il existera)
    provider = ScriptedProvider()
    events = InMemoryEventLog()  # le chat reste en mémoire cette semaine
    projects: ProjectStore
    lifecycle: Lifecycle
    url = os.environ.get(ENV_DATABASE_URL)
    if url and profile in _PERSISTENT_PROFILES:
        engine = make_engine(url)  # ne se connecte pas : les migrations viennent au démarrage
        projects = PostgresProjectStore(engine)
        stores = postgres_stores(engine)
        lifecycle = DatabaseLifecycle(url, engine)
    else:
        projects = InMemoryProjectStore()
        stores = _memory_stores()
        lifecycle = NoLifecycle()
    # 3. Services du cœur
    return App(
        profile=profile,
        projects=projects,
        events=events,
        turns=TurnService(provider, events),
        stores=stores,
        lifecycle=lifecycle,
    )
