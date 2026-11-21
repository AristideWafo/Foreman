"""Choix de l'adaptateur de modèle : rejeu en CI et en EVAL, vrai LLM partout ailleurs.

Le rejeu est FORCÉ en CI (variable `CI`) et pour le profil EVAL : aucun appel réseau ni payant.
Ailleurs, le rejeu n'est jamais consulté : sans clé ni modèle en base, le vrai provider lève
`LlmNotConfigured` et le tour échoue avec `llm_not_configured` (pas de repli silencieux).
"""

import os
from typing import Any

from foreman.core.catalog import Catalog, ToolDefinition
from foreman.core.llm import LlmSettings
from foreman.core.ports import Provider
from foreman.core.secrets import SecretStore
from foreman.core.turn import MAX_READS_PER_ROUND
from foreman.core.turn_budget import MAX_TOOL_ROUNDS
from foreman.infra.llm_settings import SecretLlmSettings
from foreman.integrations.anthropic.provider import (
    SYSTEM_PROMPT,
    WRITE_TOOLS_HEADING,
    AnthropicProvider,
    to_wire,
)


def _available(catalog: Catalog) -> list[ToolDefinition]:
    """Outils des connecteurs `available` (les « bientôt disponibles » restent cachés du modèle)."""
    live = {n for n, c in catalog.connectors.items() if c.availability == "available"}
    return [t for t in catalog.tools.values() if t.connector in live]


def read_tool_definitions(catalog: Catalog) -> list[dict[str, Any]]:
    """Seuls les outils `read` deviennent des outils du modèle ; la gateway valide les paramètres
    (`strict: false`), les écritures ne passent que par `propose_plan`."""
    return [
        {
            "name": to_wire(t.name),
            "description": t.description or t.name,
            "strict": False,
            "input_schema": t.input,
        }
        for t in _available(catalog)
        if t.tool_class == "read"
    ]


def build_prompt(catalog: Catalog) -> str:
    """Prompt système + écritures possibles (nom, paramètres, requis*) lues du catalogue."""
    lines = []
    for t in _available(catalog):
        if t.tool_class == "read":
            continue
        props = t.input.get("properties")
        required = t.input.get("required")
        names = sorted(props) if isinstance(props, dict) else []
        req = set(required) if isinstance(required, list) else set()
        lines.append(f"- {t.name}({', '.join(n + '*' if n in req else n for n in names)})")
    limits = (
        f"Limites : au plus {MAX_READS_PER_ROUND} appels de lecture par réponse et "
        f"{MAX_TOOL_ROUNDS} réponses de lecture par tour ; une lecture au-delà est refusée "
        "(limit_reached) et n'a rien lu. Dis-le plutôt que de deviner ce qu'elle aurait renvoyé."
    )
    return SYSTEM_PROMPT + "\n" + limits + "\n\n" + WRITE_TOOLS_HEADING + "\n" + "\n".join(lines)


def choose_provider(
    replay: Provider,
    secrets: SecretStore,
    *,
    force_replay: bool,
    catalog: Catalog,
    settings: LlmSettings | None = None,
) -> Provider:
    """`force_replay` : profil EVAL. La variable `CI` force aussi le rejeu."""
    if force_replay or os.environ.get("CI"):
        return replay
    # Relit clé et modèle à CHAQUE appel (la page d'admin peut les changer en vol).
    return AnthropicProvider(
        settings or SecretLlmSettings(secrets),
        read_tools=read_tool_definitions(catalog),
        prompt=build_prompt(catalog),
    )
