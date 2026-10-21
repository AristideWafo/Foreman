"""`AnthropicProvider` : `Provider` sur l'API Messages d'Anthropic.

Sans état entre requêtes : clé et modèle sont relus à chaque appel (`LlmSettings`), le client est
créé puis fermé pour l'appel. Aucune exception du SDK ne sort (elle citerait la requête) : elle
devient `ProviderFailed`, sans cause attachée, que le tour traduit en `internal_error`.

Contraintes des modèles récents : `tool_choice` reste `auto` (un choix forcé renvoie 400),
`strict: true` garantit des arguments conformes, l'effort est explicite.

shortcut: le mode strict n'accepte que des objets fermés. Les `params` d'une étape et la `stack`
sont libres : ils voyagent en chaînes JSON (`params_json`, `stack_json`) décodées ici ; le schéma
de `TurnService` valide ensuite le résultat comme pour le rejeu.
"""

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

import anthropic
import httpx2

from foreman.core.llm import LlmNotConfigured, LlmSettings
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.core.pricing import Usage

log = logging.getLogger(__name__)

DEFAULT_EFFORT: Final = "medium"
DEFAULT_MAX_TOKENS: Final = 8192
REFUSAL_TEXT: Final = "Je ne peux pas traiter cette demande."
SYSTEM_PROMPT: Final = (
    "Tu es Foreman, un assistant qui prépare des plans d'infrastructure. Tu ne fais rien "
    "toi-même : tu proposes un plan avec l'outil propose_plan, ou tu poses des questions avec "
    "ask_user quand une information manque. Réponds en français."
)

_STR: Final = {"type": "string"}
TOOLS: Final[list[dict[str, Any]]] = [
    {
        "name": "propose_plan",
        "description": "Propose un plan d'étapes outillées, que l'utilisateur validera.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "summary", "environment", "skills", "stack_json", "steps"],
            "properties": {
                "title": _STR,
                "summary": _STR,
                "environment": _STR,
                "skills": {"type": "array", "items": _STR},
                "stack_json": {**_STR, "description": "Objet JSON nom -> valeur, '{}' si vide."},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "tool", "params_json"],
                        "properties": {
                            "title": _STR,
                            "tool": _STR,
                            "params_json": {**_STR, "description": "Objet JSON des paramètres."},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "ask_user",
        "description": "Pose des questions à l'utilisateur quand une information manque.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["questions"],
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["field", "prompt"],
                        "properties": {"field": _STR, "prompt": _STR},
                    },
                }
            },
        },
    },
]


class ProviderFailed(Exception):
    """L'appel au modèle a échoué. Message fixe : aucun détail du SDK."""

    def __init__(self) -> None:
        super().__init__("appel au modèle en échec")


def _json_object(raw: object) -> object:
    """Décode une chaîne JSON en objet ; sinon renvoie la valeur telle quelle (refusée en aval)."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def decode_arguments(name: str, raw: Mapping[str, object]) -> dict[str, object]:
    """Remet `propose_plan` à la forme attendue par `ProposePlanArguments`."""
    if name != "propose_plan":
        return dict(raw)
    args = {k: v for k, v in raw.items() if k != "stack_json"}
    if (stack := _json_object(raw.get("stack_json"))) not in ({}, None):
        args["stack"] = stack
    if not args.get("skills"):
        args.pop("skills", None)
    steps = raw.get("steps")
    if isinstance(steps, list):
        args["steps"] = [
            {
                **{k: v for k, v in s.items() if k != "params_json"},
                "params": _json_object(s.get("params_json")),
            }
            if isinstance(s, dict)
            else s
            for s in steps
        ]
    return args


class AnthropicProvider:
    def __init__(
        self,
        settings: LlmSettings,
        *,
        http_client: httpx2.AsyncClient | None = None,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._settings = settings
        self._http_client = http_client
        self._effort = effort
        self._max_tokens = max_tokens

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        key = await self._settings.api_key()
        model = await self._settings.model()
        if key is None or not model:
            raise LlmNotConfigured
        client = anthropic.AsyncAnthropic(
            api_key=key.get_secret_value(), http_client=self._http_client
        )
        del key
        try:
            message = await client.messages.create(  # type: ignore[call-overload]
                model=model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": m.role, "content": m.text} for m in messages],
                tools=TOOLS,
                tool_choice={"type": "auto"},
                output_config={"effort": self._effort},
            )
        except anthropic.APIError as exc:
            # Seuls le type et le statut sont journalisés : le message peut citer la requête.
            log.warning(
                "llm_call_failed type=%s status=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise ProviderFailed from None
        finally:
            if self._http_client is None:
                await client.close()
        return self._reply(message, model)

    @staticmethod
    def _reply(message: anthropic.types.Message, model: str) -> ModelReply:
        usage = Usage(
            model=model,  # le modèle DEMANDÉ : c'est lui qui a un tarif déclaré
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
        )
        if message.stop_reason == "refusal":
            return ModelReply(text=REFUSAL_TEXT, usage=usage)
        if message.stop_reason == "max_tokens":
            log.warning("llm_truncated model=%s", model)
            raise ProviderFailed  # des arguments d'outil tronqués ne sont pas fiables
        text = "".join(b.text for b in message.content if b.type == "text")
        calls = tuple(
            ToolCall(b.name, decode_arguments(b.name, b.input))
            for b in message.content
            if b.type == "tool_use"
        )
        return ModelReply(text=text, tool_calls=calls, usage=usage)
