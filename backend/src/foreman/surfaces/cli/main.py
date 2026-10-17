import asyncio
import sys

from foreman.bootstrap.configure import Profile, configure
from foreman.core.turn import TurnRequest


def main() -> None:
    app = configure(Profile.CLI)
    message = " ".join(sys.argv[1:])
    result = asyncio.run(app.turns.run(TurnRequest(user_id="cli", message=message)))
    sys.stdout.write(result.reply + "\n")
