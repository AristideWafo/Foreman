"""Réglages du LLM (clé et modèle) : relus à CHAQUE appel, jamais gardés en attribut."""

from typing import Protocol

from pydantic import SecretStr

LLM_KEY_ID = "llm.api_key"
LLM_KEY_KIND = "llm_api_key"
LLM_MODEL_ID = "llm.model"
LLM_MODEL_KIND = "llm_model"
# Fournisseur réel choisi (`anthropic` par défaut, `strands`) : pas un secret, relu à chaque appel.
LLM_PROVIDER_ID = "llm.provider"
LLM_PROVIDER_KIND = "llm_provider"
LLM_PROVIDERS = ("anthropic", "strands")
DEFAULT_LLM_PROVIDER = "anthropic"


class LlmNotConfigured(Exception):
    """Aucune clé ou aucun modèle n'est configuré. Message fixe."""

    def __init__(self) -> None:
        super().__init__("LLM non configuré")


class ProviderFailed(Exception):
    """L'appel au modèle a échoué. Message fixe : aucun détail du SDK."""

    def __init__(self) -> None:
        super().__init__("appel au modèle en échec")


class LlmSettings(Protocol):
    async def api_key(self) -> SecretStr | None:
        """Déchiffre la clé à la demande. L'appelant ne la conserve pas."""
        ...

    async def model(self) -> str | None: ...
