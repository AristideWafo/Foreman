"""`StrandsProvider` : `Provider` sur un modèle Strands Agents (ADR 0004).

Strands n'est utilisé QUE comme couche modèle/streaming : on appelle `Model.stream` et on agrège
les événements en `ModelReply`. Aucun `strands.Agent`, aucun outil Strands, aucune boucle
d'événements Strands : Strands ne peut exécuter aucun outil. Les appels d'outils reviennent au
`TurnService`, qui les fait passer par la gateway (seul chemin, ADR 0003).

Sans état entre requêtes : clé et modèle sont relus à chaque appel (`LlmSettings`), le modèle et son
client sont créés puis fermés pour l'appel. Aucune exception de Strands ou du SDK ne sort (elle
citerait la requête) : elle devient `ProviderFailed`, sans cause attachée.

shortcut: Strands ne transmet pas `strict: true` des outils ; la validation par schéma du
`TurnService` reste l'autorité (comme pour le rejeu).
"""

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Final, Protocol

import anthropic
from strands.models.anthropic import AnthropicModel

from foreman.core.llm import LlmNotConfigured, LlmSettings, ProviderFailed
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.pricing import Usage

log = logging.getLogger(__name__)
# Strands journalise la requête complète en DEBUG (historique, résultats d'outils) : coupé.
logging.getLogger("strands").setLevel(logging.WARNING)

DEFAULT_EFFORT: Final = "medium"
DEFAULT_MAX_TOKENS: Final = 8192
REFUSAL_TEXT: Final = "Je ne peux pas traiter cette demande."


class StreamingModel(Protocol):
    """Sous-ensemble de `strands.models.Model` utilisé ici : le streaming, rien d'autre."""

    def stream(
        self,
        messages: list[dict[str, Any]],
        tool_specs: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        *,
        tool_choice: dict[str, Any] | None = None,
    ) -> AsyncIterator[Mapping[str, Any]]: ...


class ModelFactory(Protocol):
    """Ouvre un modèle Strands pour UN appel (clé en clair seulement le temps de l'appel)."""

    def open(self, api_key: str, model_id: str) -> AbstractAsyncContextManager[StreamingModel]: ...


class WireCodec(Protocol):
    """Noms d'outils au format de l'API et arguments décodés (fournis par la composition)."""

    def to_wire(self, name: str) -> str: ...

    def decode(self, wire_name: str, raw: Mapping[str, object]) -> ToolCall: ...


class AnthropicModels:
    """Fabrique réelle : `AnthropicModel` de Strands, sur un client fermé après l'appel."""

    def __init__(
        self, *, effort: str = DEFAULT_EFFORT, max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> None:
        self._effort = effort
        self._max_tokens = max_tokens

    @asynccontextmanager
    async def open(self, api_key: str, model_id: str) -> AsyncIterator[StreamingModel]:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            yield AnthropicModel(  # type: ignore[misc]
                client=client,
                model_id=model_id,
                max_tokens=self._max_tokens,
                params={"output_config": {"effort": self._effort}},
            )
        finally:
            await client.close()


def tool_specs(tools: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Définitions au format de l'API (`name`, `description`, `input_schema`) -> `ToolSpec`."""
    return [
        {
            "name": t["name"],
            "description": t.get("description") or t["name"],
            "inputSchema": {"json": t["input_schema"]},
        }
        for t in tools
    ]


def strands_messages(
    messages: Sequence[ConversationMessage], codec: WireCodec
) -> list[dict[str, Any]]:
    """Historique -> messages Strands. Les résultats d'outils voyagent en blocs `toolResult`
    (jamais en texte `user`), dans une enveloppe qui les déclare non fiables."""
    names: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.tool_results:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": r.call_id,
                                "status": "error" if r.is_error else "success",
                                "content": [
                                    {
                                        "text": json.dumps(
                                            {
                                                "tool": names.get(r.call_id, "inconnu"),
                                                "untrusted_data": r.text,
                                            },
                                            ensure_ascii=False,
                                        )
                                    }
                                ],
                            }
                        }
                        for r in m.tool_results
                    ],
                }
            )
        elif m.tool_calls:
            names.update({c.id: c.name for c in m.tool_calls})
            blocks: list[dict[str, Any]] = [{"text": m.text}] if m.text else []
            blocks += [
                {
                    "toolUse": {
                        "toolUseId": c.id,
                        "name": codec.to_wire(c.name),
                        "input": dict(c.arguments),
                    }
                }
                for c in m.tool_calls
            ]
            out.append({"role": m.role, "content": blocks})
        else:
            out.append({"role": m.role, "content": [{"text": m.text}]})
    return out


class _Reply:
    """Agrège les événements de `Model.stream` (texte, blocs `toolUse`, arrêt, usage)."""

    def __init__(self) -> None:
        self.text: list[str] = []
        self.tools: list[tuple[str, str, list[str]]] = []  # (id, nom au format API, json partiel)
        self.stop: str | None = None
        self.usage: Mapping[str, Any] = {}

    def add(self, event: Mapping[str, Any]) -> None:
        if (start := event.get("contentBlockStart")) is not None:
            use = start.get("start", {}).get("toolUse")
            if use is not None:
                self.tools.append((use["toolUseId"], use["name"], []))
        elif (delta := event.get("contentBlockDelta")) is not None:
            d = delta.get("delta", {})
            if "text" in d:
                self.text.append(d["text"])
            elif "toolUse" in d and self.tools:
                self.tools[-1][2].append(d["toolUse"].get("input", ""))
        elif (stop := event.get("messageStop")) is not None:
            self.stop = stop.get("stopReason")
        elif (meta := event.get("metadata")) is not None:
            self.usage = meta.get("usage") or {}


class StrandsProvider:
    def __init__(
        self,
        settings: LlmSettings,
        codec: WireCodec,
        *,
        models: ModelFactory | None = None,
        tools: Sequence[Mapping[str, Any]] = (),
        prompt: str = "",
    ) -> None:
        self._settings = settings
        self._codec = codec
        self._models = models or AnthropicModels()
        self._tool_specs = tool_specs(tools)
        self._prompt = prompt

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        key = await self._settings.api_key()
        model_id = await self._settings.model()
        if key is None or not model_id:
            raise LlmNotConfigured
        reply = _Reply()
        try:
            async with self._models.open(key.get_secret_value(), model_id) as model:
                del key
                async for event in model.stream(
                    strands_messages(messages, self._codec),
                    self._tool_specs,
                    self._prompt,
                    tool_choice={"auto": {}},
                ):
                    reply.add(event)
        except Exception as exc:
            # Seul le type est journalisé : le message peut citer la requête ou la clé.
            log.warning("llm_call_failed provider=strands type=%s", type(exc).__name__)
            raise ProviderFailed from None
        return self._reply(reply, model_id)

    def _reply(self, reply: _Reply, model_id: str) -> ModelReply:
        u = reply.usage
        usage = Usage(
            model=model_id,  # le modèle DEMANDÉ : c'est lui qui a un tarif déclaré
            input_tokens=int(u.get("inputTokens", 0)),
            output_tokens=int(u.get("outputTokens", 0)),
            cache_read_tokens=int(u.get("cacheReadInputTokens", 0)),
            cache_write_tokens=int(u.get("cacheWriteInputTokens", 0)),
        )
        if reply.stop == "refusal":
            return ModelReply(text=REFUSAL_TEXT, usage=usage)
        if reply.stop == "max_tokens":
            log.warning("llm_truncated provider=strands model=%s", model_id)
            raise ProviderFailed  # des arguments d'outil tronqués ne sont pas fiables
        calls = []
        for call_id, wire_name, parts in reply.tools:
            try:
                raw = json.loads("".join(parts) or "{}")
            except ValueError:
                raise ProviderFailed from None
            if not isinstance(raw, dict):
                raise ProviderFailed
            decoded = self._codec.decode(wire_name, raw)
            calls.append(ToolCall(decoded.name, decoded.arguments, call_id))
        return ModelReply(text="".join(reply.text), tool_calls=tuple(calls), usage=usage)
