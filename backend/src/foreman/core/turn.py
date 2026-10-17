"""Service de tour partagé par toutes les surfaces."""

from dataclasses import dataclass

from foreman.core.ports import Provider


@dataclass(frozen=True, slots=True)
class TurnRequest:
    user_id: str
    message: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    reply: str


class TurnService:
    """Point d'entrée unique de la logique d'agent (web, CLI et webhooks l'appellent)."""

    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    async def run(self, request: TurnRequest) -> TurnResult:
        reply = await self._provider.complete([request.message])
        return TurnResult(reply=reply.text)
