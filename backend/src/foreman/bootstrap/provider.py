"""Choix de l'adaptateur de modèle : vrai LLM si configuré, sinon rejeu.

Le rejeu est FORCÉ en CI (variable `CI`) et pour le profil EVAL : aucun appel réseau ni payant.
Quand le vrai provider est actif, le rejeu (et son entrée `default`) n'est jamais consulté, et une
erreur du vrai provider n'y retombe pas : pas de repli silencieux.
"""

import os
from collections.abc import Sequence

from foreman.core.llm import LLM_KEY_ID, LLM_MODEL_ID, LlmSettings
from foreman.core.ports import ConversationMessage, ModelReply, Provider
from foreman.core.secrets import SecretStore
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.integrations.anthropic.provider import AnthropicProvider


class ConfiguredProvider:
    """Relit à CHAQUE appel si un LLM est configuré (la page d'admin peut le changer en vol)."""

    def __init__(self, replay: Provider, real: Provider, secrets: SecretStore) -> None:
        self._replay = replay
        self._real = real
        self._secrets = secrets

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        if await self._secrets.exists(LLM_KEY_ID) and await self._secrets.exists(LLM_MODEL_ID):
            return await self._real.complete(messages)
        return await self._replay.complete(messages)


def choose_provider(
    replay: Provider,
    secrets: SecretStore,
    *,
    force_replay: bool,
    settings: LlmSettings | None = None,
) -> Provider:
    """`force_replay` : profil EVAL. La variable `CI` force aussi le rejeu."""
    if force_replay or os.environ.get("CI"):
        return replay
    real = AnthropicProvider(settings or SecretLlmSettings(secrets))
    return ConfiguredProvider(replay, real, secrets)
