"""Configuration du processus. L'ordre des étapes est fixe : un profil ne peut pas le changer."""

import logging
import os
from dataclasses import dataclass
from enum import StrEnum

from foreman.config.env import DEFAULT_LOG_LEVEL, ENV_LOG_LEVEL
from foreman.core.turn import TurnService
from foreman.infra.echo_provider import EchoProvider


class Profile(StrEnum):
    WEB = "web"
    CLI = "cli"
    WORKER = "worker"
    EVAL = "eval"


@dataclass(frozen=True, slots=True)
class App:
    profile: Profile
    turns: TurnService


def configure(profile: Profile) -> App:
    # 1. Journalisation propre au processus
    logging.basicConfig(level=os.environ.get(ENV_LOG_LEVEL, DEFAULT_LOG_LEVEL))
    # 2. Adaptateurs (un seul endroit : voir adapters.py quand il existera)
    provider = EchoProvider()
    # 3. Services du cœur
    return App(profile=profile, turns=TurnService(provider))
