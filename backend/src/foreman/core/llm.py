"""Réglages du LLM (clé et modèle) : relus à CHAQUE appel, jamais gardés en attribut."""

from typing import Protocol

from pydantic import SecretStr

LLM_KEY_ID = "llm.api_key"
LLM_KEY_KIND = "llm_api_key"
LLM_MODEL_ID = "llm.model"
LLM_MODEL_KIND = "llm_model"


class LlmNotConfigured(Exception):
    """Aucune clé ou aucun modèle n'est configuré. Message fixe."""

    def __init__(self) -> None:
        super().__init__("LLM non configuré")


class LlmSettings(Protocol):
    async def api_key(self) -> SecretStr | None:
        """Déchiffre la clé à la demande. L'appelant ne la conserve pas."""
        ...

    async def model(self) -> str | None: ...
