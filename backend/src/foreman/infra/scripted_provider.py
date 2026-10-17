"""Faux agent déterministe et sans état, utilisé tant qu'aucun vrai modèle n'est branché."""

from collections.abc import Sequence

from foreman.core.ports import ModelReply, ToolCall

_PLAN = {
    "title": "Plan de démonstration",
    "summary": "Trois étapes jouées par le faux agent, sans effet réel.",
    "steps": [
        {"title": "Préparer le dépôt"},
        {"title": "Configurer l'intégration continue"},
        {"title": "Déployer l'environnement"},
    ],
}


class ScriptedProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        last = messages[-1] if messages else ""
        return ModelReply(
            text=f"Reçu : {last}",
            tool_calls=(ToolCall(name="propose_plan", arguments=_PLAN),),
        )
