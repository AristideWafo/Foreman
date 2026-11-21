"""Bascule du fournisseur RÉEL : `anthropic` (défaut, repli) ou `strands` (ADR 0004).

Le réglage `llm.provider` est relu à CHAQUE appel (`foreman llm set-provider`) : pas de redémarrage.
Une erreur d'un fournisseur ne bascule jamais vers l'autre : pas de repli silencieux.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from foreman.core.llm import LlmSettings
from foreman.core.ports import ConversationMessage, ModelReply, Provider, ToolCall
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.integrations.anthropic.provider import TOOLS, decode_arguments, from_wire, to_wire
from foreman.integrations.strands.provider import ModelFactory, StrandsProvider


class AnthropicWireCodec:
    """Noms `to_wire`/`from_wire` et décodage de `propose_plan` d'`AnthropicProvider`."""

    def to_wire(self, name: str) -> str:
        return to_wire(name)

    def decode(self, wire_name: str, raw: Mapping[str, object]) -> ToolCall:
        name = from_wire(wire_name)
        return ToolCall(name, decode_arguments(name, raw))


def strands_provider(
    settings: LlmSettings,
    read_tools: Sequence[Mapping[str, Any]],
    prompt: str,
    models: ModelFactory | None = None,
) -> StrandsProvider:
    """Mêmes outils (`propose_plan`, `ask_user`, lectures) et prompt qu'`AnthropicProvider`."""
    return StrandsProvider(
        settings, AnthropicWireCodec(), models=models, tools=[*TOOLS, *read_tools], prompt=prompt
    )


class SwitchedProvider:
    """Délègue au fournisseur choisi par `llm.provider` (inconnu ou absent : `anthropic`)."""

    def __init__(self, settings: SecretLlmSettings, anthropic: Provider, strands: Provider) -> None:
        self._settings = settings
        self._providers = {"anthropic": anthropic, "strands": strands}

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        return await self._providers[await self._settings.provider()].complete(messages)
