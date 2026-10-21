"""Réglages du LLM lus dans le magasin de secrets (aucune copie en clair en attribut).

shortcut: le modèle choisi vit aussi dans le magasin de secrets (chiffré, sans enjeu) pour éviter
une migration ; le déplacer dans une table de réglages quand la page d'administration existera.
"""

from pydantic import SecretStr

from foreman.core.llm import LLM_KEY_ID, LLM_KEY_KIND, LLM_MODEL_ID, LLM_MODEL_KIND
from foreman.core.secrets import SecretStore


class SecretLlmSettings:
    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets

    async def api_key(self) -> SecretStr | None:
        return await self._secrets.get(LLM_KEY_ID, LLM_KEY_KIND)

    async def model(self) -> str | None:
        value = await self._secrets.get(LLM_MODEL_ID, LLM_MODEL_KIND)
        return None if value is None else value.get_secret_value()
