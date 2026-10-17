"""Fournisseur de démonstration, utilisé tant qu'aucun vrai modèle n'est branché."""

from collections.abc import Sequence

from foreman.core.ports import ModelReply


class EchoProvider:
    async def complete(self, messages: Sequence[str]) -> ModelReply:
        return ModelReply(text=messages[-1] if messages else "")
