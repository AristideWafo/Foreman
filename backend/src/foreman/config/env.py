"""Noms des variables d'environnement."""

from typing import Final

ENV_PROFILE: Final = "FOREMAN_PROFILE"
ENV_LOG_LEVEL: Final = "FOREMAN_LOG_LEVEL"
ENV_DATABASE_URL: Final = "FOREMAN_DATABASE_URL"
ENV_TEST_DATABASE_URL: Final = "FOREMAN_TEST_DATABASE_URL"
# "1" autorise un retour arrière qui supprime des données d'audit (tests, exploitation).
ENV_ALLOW_DESTRUCTIVE_DOWNGRADE: Final = "FOREMAN_ALLOW_DESTRUCTIVE_DOWNGRADE"

DEFAULT_LOG_LEVEL: Final = "INFO"
ENV_STATIC_DIR: Final = "FOREMAN_STATIC_DIR"
ENV_VERSION: Final = "FOREMAN_VERSION"
DEFAULT_VERSION: Final = "dev"
