import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime

from foreman.bootstrap.configure import App, Profile, configure
from foreman.config.env import DEFAULT_PUBLIC_URL, ENV_PUBLIC_URL
from foreman.core.accounts import AccountError
from foreman.core.auth import create_admin_invitation
from foreman.core.store import DEV_TEAM_ID, DEV_USER_ID
from foreman.core.turn import TurnRequest


async def _run(app: App, message: str) -> list[str]:
    project = await app.projects.create("", DEV_TEAM_ID, DEV_USER_ID)
    turn_id = app.turns.begin(project.id)
    request = TurnRequest(user_id=DEV_USER_ID, project_id=project.id, message=message)
    await app.turns.run(request, turn_id)
    events = await app.events.read_after(project.id, 0)
    return [e.data.text for e in events if e.type == "message" and e.data.role == "assistant"]


async def _admin_create(email: str) -> str:
    app = configure(Profile.ADMIN)
    assert app.accounts is not None and app.auth is not None  # noqa: S101 - garanti par configure
    await app.lifecycle.start()  # migrations
    try:
        token = await create_admin_invitation(app.accounts, app.auth, email, datetime.now(UTC))
    finally:
        await app.lifecycle.stop()
    base = os.environ.get(ENV_PUBLIC_URL, DEFAULT_PUBLIC_URL).rstrip("/")
    return f"{base}/accept-invite#token={token}"  # fragment : absent des journaux d'accès


def _admin(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="foreman admin")
    parser.add_argument("action", choices=["create"])
    parser.add_argument("--email", required=True)
    args = parser.parse_args(argv)
    try:
        link = asyncio.run(_admin_create(args.email))
    except AccountError:
        sys.exit("création impossible : compte déjà actif ou invitation refusée")
    # Sortie standard SEULEMENT : le lien contient le jeton, il ne passe par aucun journal.
    sys.stdout.write(link + "\n")


def main() -> None:
    if sys.argv[1:2] == ["admin"]:
        return _admin(sys.argv[2:])
    app = configure(Profile.CLI)
    replies = asyncio.run(_run(app, " ".join(sys.argv[1:])))
    sys.stdout.write("\n".join(replies) + "\n")
