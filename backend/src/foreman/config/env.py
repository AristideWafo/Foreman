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

ENV_CATALOG_DIR: Final = "FOREMAN_CATALOG_DIR"
DEFAULT_CATALOG_DIR: Final = "catalog"

ENV_ENVIRONMENT: Final = "FOREMAN_ENVIRONMENT"
DEFAULT_ENVIRONMENT: Final = "staging"

# "none" (défaut) : utilisateur `dev`, en-tête ignoré. "proxy_header" : identité posée par Traefik.
# "session" : mot de passe et cookie de session (PostgreSQL requis).
ENV_AUTH_MODE: Final = "FOREMAN_AUTH_MODE"
DEFAULT_AUTH_MODE: Final = "none"
# `nom:role,nom:role` : rôles des membres, lus du `.env` du serveur (jamais du dépôt).
ENV_DEV_MEMBERS: Final = "FOREMAN_DEV_MEMBERS"
# "0" retire l'attribut Secure du cookie de session (développement local en HTTP uniquement).
ENV_COOKIE_SECURE: Final = "FOREMAN_COOKIE_SECURE"
# Base des liens d'invitation affichés par `foreman admin create`.
ENV_PUBLIC_URL: Final = "FOREMAN_PUBLIC_URL"
DEFAULT_PUBLIC_URL: Final = "http://localhost:8000"

# Clé maître des secrets : créée au premier démarrage dans un volume dédié (docs/DEPLOYMENT.md).
ENV_SECRETS_KEY_FILE: Final = "FOREMAN_SECRETS_KEY_FILE"
DEFAULT_SECRETS_KEY_FILE: Final = "/var/lib/foreman/secrets/master.key"
