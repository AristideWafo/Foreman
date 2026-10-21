import argparse
import asyncio
import sys
from datetime import UTC, datetime

from foreman.bootstrap.configure import App, Profile, configure, invitation_link
from foreman.bootstrap.llm import RecordRefused, record_llm_response, set_llm_key, set_llm_model
from foreman.bootstrap.secrets import rotate_master_key
from foreman.core.accounts import AccountError
from foreman.core.auth import create_admin_invitation
from foreman.core.secrets import SecretError
from foreman.core.store import DEV_TEAM_ID, DEV_USER_ID, StoreError
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
    return invitation_link(token)


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


async def _secrets_rotate(prune: bool) -> int:
    app = configure(Profile.ADMIN)
    assert app.key_file is not None  # noqa: S101 - garanti par configure (base obligatoire)
    await app.lifecycle.start()  # migrations puis chargement de la clé
    try:
        return await rotate_master_key(app.key_file, app.secrets, prune=prune)
    finally:
        await app.lifecycle.stop()


def _secrets(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="foreman secrets")
    parser.add_argument("action", choices=["rotate"])
    parser.add_argument("--prune", action="store_true", help="retire les anciennes clés du fichier")
    args = parser.parse_args(argv)
    try:
        count = asyncio.run(_secrets_rotate(args.prune))
    except (RuntimeError, SecretError, StoreError):
        sys.exit("rotation impossible : voir les journaux et docs/DEPLOYMENT.md")
    sys.stdout.write(f"{count} secret(s) rechiffré(s)\n")


async def _llm_record(name: str, message: str) -> str:
    app = configure(Profile.ADMIN)
    await app.lifecycle.start()
    try:
        return str(await record_llm_response(app, name, message))
    finally:
        await app.lifecycle.stop()


async def _llm_set(action: str, value: str) -> None:
    app = configure(Profile.ADMIN)
    await app.lifecycle.start()
    try:
        await (set_llm_key if action == "set-key" else set_llm_model)(app, value)
    finally:
        await app.lifecycle.stop()


def _llm(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="foreman llm")
    parser.add_argument("action", choices=["record", "set-key", "set-model"])
    parser.add_argument("--name", help="record : nom du fichier (a-z, 0-9, tirets)")
    parser.add_argument("--message", help="record : message utilisateur à envoyer")
    parser.add_argument("--model", help="set-model : identifiant dans la liste déclarée")
    args = parser.parse_args(argv)
    try:
        if args.action == "set-key":
            # La clé vient de l'entrée standard : jamais d'argument (historique du shell, ps).
            asyncio.run(_llm_set("set-key", sys.stdin.read()))
            sys.stdout.write("clé enregistrée\n")
            return
        if args.action == "set-model":
            asyncio.run(_llm_set("set-model", args.model or ""))
            sys.stdout.write("modèle enregistré\n")
            return
        if not args.name or not args.message:
            sys.exit("record exige --name et --message")
        path = asyncio.run(_llm_record(args.name, args.message))
    except RecordRefused as exc:
        sys.exit(f"enregistrement impossible : {exc}")
    except Exception:
        sys.exit("enregistrement impossible : voir les journaux")
    sys.stdout.write(f"{path}\n")


def main() -> None:
    if sys.argv[1:2] == ["llm"]:
        return _llm(sys.argv[2:])
    if sys.argv[1:2] == ["admin"]:
        return _admin(sys.argv[2:])
    if sys.argv[1:2] == ["secrets"]:
        return _secrets(sys.argv[2:])
    app = configure(Profile.CLI)
    replies = asyncio.run(_run(app, " ".join(sys.argv[1:])))
    sys.stdout.write("\n".join(replies) + "\n")
