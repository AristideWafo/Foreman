"""Configuration du processus. L'ordre des étapes est fixe : un profil ne peut pas le changer."""

import logging
import os
from dataclasses import dataclass
from enum import StrEnum

from foreman.config.env import DEFAULT_LOG_LEVEL, ENV_LOG_LEVEL
from foreman.core.ports import EventLog, ProjectStore
from foreman.core.turn import TurnService
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


def configure(profile: Profile) -> App:
    # 1. Journalisation propre au processus
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    # 2. Adaptateurs (un seul endroit : voir adapters.py quand il existera)
    provider = ScriptedProvider()
    projects = InMemoryProjectStore()
    events = InMemoryEventLog()
    # 3. Services du cœur
    return App(
        profile=profile, projects=projects, events=events, turns=TurnService(provider, events)
    )
