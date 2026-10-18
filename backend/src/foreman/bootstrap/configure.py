"""Configuration du processus. L'ordre des étapes est fixe : un profil ne peut pas le changer."""

import logging
import os
from dataclasses import dataclass
from enum import StrEnum

from foreman.config.env import (
    DEFAULT_ENVIRONMENT,
    DEFAULT_LOG_LEVEL,
    ENV_ENVIRONMENT,
    ENV_LOG_LEVEL,
)
from foreman.core.catalog import Catalog
from foreman.core.ports import EventLog, ProjectStore
from foreman.core.turn import TurnService
from foreman.infra.file_catalog import load_catalog
from foreman.infra.in_memory import InMemoryEventLog, InMemoryProjectStore
from foreman.infra.scripted_provider import ScriptedProvider


class Profile(StrEnum):
    WEB = "web"
    CLI = "cli"
    WORKER = "worker"
    EVAL = "eval"


@dataclass(frozen=True, slots=True)
class App:
    profile: Profile
    projects: ProjectStore
    events: EventLog
    turns: TurnService
    catalog: Catalog | None = (
        None  # chargé au démarrage par `configure` ; absent dans certains tests
    )


def configure(profile: Profile) -> App:
    # 1. Journalisation propre au processus
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    # 2. Catalogue : synchrone, avant la boucle asynchrone. Une erreur (fichier invalide, Skill
    #    brouillon hors staging, dossier absent) arrête le démarrage avec un message clair.
    environment = os.environ.get(ENV_ENVIRONMENT, DEFAULT_ENVIRONMENT)
    catalog = load_catalog(environment=environment)
    # 3. Adaptateurs (un seul endroit : voir adapters.py quand il existera)
    provider = ScriptedProvider()
    projects = InMemoryProjectStore()
    events = InMemoryEventLog()
    # 4. Services du cœur
    return App(
        profile=profile,
        projects=projects,
        events=events,
        turns=TurnService(provider, events),
        catalog=catalog,
    )
