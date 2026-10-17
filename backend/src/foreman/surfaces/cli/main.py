import asyncio
import sys

from foreman.bootstrap.configure import App, Profile, configure
from foreman.core.turn import TurnRequest


async def _run(app: App, message: str) -> list[str]:
    project = await app.projects.create("")
    turn_id = app.turns.begin(project.id)
    await app.turns.run(TurnRequest(user_id="cli", project_id=project.id, message=message), turn_id)
    events = await app.events.read_after(project.id, 0)
    return [e.data.text for e in events if e.type == "message" and e.data.role == "assistant"]


def main() -> None:
    app = configure(Profile.CLI)
    replies = asyncio.run(_run(app, " ".join(sys.argv[1:])))
    sys.stdout.write("\n".join(replies) + "\n")
