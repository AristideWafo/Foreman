from collections.abc import Sequence

from foreman.core.ports import ModelReply
from foreman.core.turn import TurnRequest, TurnService


class FakeProvider:
    """Fake nommé : renvoie le nombre de messages reçus."""

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        return ModelReply(text=f"{len(messages)}:{messages[-1]}")


async def test_turn_returns_provider_reply() -> None:
    result = await TurnService(FakeProvider()).run(TurnRequest(user_id="u", message="salut"))
    assert result.reply == "1:salut"
