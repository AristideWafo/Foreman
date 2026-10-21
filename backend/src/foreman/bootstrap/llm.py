"""Commande de développement `foreman llm record` : enregistre UNE vraie réponse du modèle.

Appel réel et payant : refusé en CI. La clé vient du magasin de secrets, jamais de l'environnement.
Seule la réponse brute `Message` (masquée) est écrite, sous `catalog/recordings/real/`.
"""

import json
import os
from pathlib import Path
from typing import Any

import httpx2
from pydantic import SecretStr

from foreman.bootstrap.configure import App
from foreman.core.gateway.redact import mask_text
from foreman.core.llm import (
    LLM_KEY_ID,
    LLM_KEY_KIND,
    LLM_MODEL_ID,
    LLM_MODEL_KIND,
    LlmNotConfigured,
)
from foreman.core.ports import ConversationMessage
from foreman.infra.file_catalog import catalog_dir_from_env
from foreman.infra.llm_recording import RecordingRefused, build_recording, write_recording
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.infra.replay_provider import sha256_of
from foreman.integrations.anthropic.models import model_prices
from foreman.integrations.anthropic.provider import AnthropicProvider

MESSAGES_PATH = "/v1/messages"


class RecordRefused(Exception):
    """Enregistrement impossible (CI, clé absente). Message fixe."""


class _Capture:
    """Garde le corps de la réponse `messages` (déjà décodé) pour l'écrire après masquage."""

    def __init__(self) -> None:
        self.body: bytes | None = None

    async def __call__(self, response: httpx2.Response) -> None:
        if response.status_code == 200 and response.request.url.path == MESSAGES_PATH:
            await response.aread()
            self.body = response.content


MAX_KEY_CHARS = 512


async def set_llm_key(app: App, key: str) -> None:
    """Chiffre la clé LLM dans le magasin de secrets. Message d'erreur sans la valeur."""
    key = key.strip()
    if not key or len(key) > MAX_KEY_CHARS or any(c.isspace() for c in key):
        raise RecordRefused("clé invalide")
    await app.secrets.put(LLM_KEY_ID, LLM_KEY_KIND, SecretStr(key), created_by="cli")


async def set_llm_model(app: App, model: str) -> None:
    """Choisit le modèle dans la liste déclarée (`connector.yaml`) ; sinon refus."""
    if model not in model_prices():
        raise RecordRefused("modèle hors de la liste déclarée")
    await app.secrets.put(LLM_MODEL_ID, LLM_MODEL_KIND, SecretStr(model), created_by="cli")


async def record_llm_response(
    app: App, name: str, message: str, catalog_dir: Path | None = None
) -> Path:
    if os.environ.get("CI"):
        raise RecordRefused("jamais en CI")
    settings = SecretLlmSettings(app.secrets)
    if await settings.api_key() is None or not await settings.model():
        raise RecordRefused("clé ou modèle non configurés")
    capture = _Capture()
    async with httpx2.AsyncClient(event_hooks={"response": [capture]}) as http:
        provider = AnthropicProvider(settings, http_client=http)
        masked = mask_text(message)  # ce qui part chez le fournisseur est masqué
        try:
            await provider.complete([ConversationMessage("user", masked)])
        except LlmNotConfigured:
            raise RecordRefused("clé ou modèle non configurés") from None
    if capture.body is None:
        raise RecordRefused("aucune réponse capturée")
    raw: Any = json.loads(capture.body)
    model = await settings.model()
    assert model is not None  # noqa: S101 - vérifié plus haut
    try:
        recording = build_recording(model, raw, last_user_sha256=sha256_of(masked))
        return write_recording(catalog_dir or catalog_dir_from_env(), name, recording)
    except RecordingRefused:
        raise RecordRefused("contenu refusé (motif de secret ou forme invalide)") from None
