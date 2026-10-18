"""Modèle rejoué : choix par hash, déterminisme, erreur typée, scénario S1."""

import copy
import hashlib
import json
import traceback
from pathlib import Path
from uuid import uuid4

import pytest

from foreman.core.turn import ProposePlanArguments, TurnRequest, TurnService
from foreman.infra.file_catalog import catalog_dir_from_env
from foreman.infra.in_memory import InMemoryEventLog
from foreman.infra.replay_provider import RecordingInvalid, RecordingNotFound, ReplayProvider


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_recording(tmp_path: Path, exchanges: str, version: str = "1") -> Path:
    path = tmp_path / "rec.yaml"
    path.write_text(f"version: {version}\nexchanges:\n{exchanges}", encoding="utf-8")
    return path


def exchange(when: str, text: str) -> str:
    return f"  - when: {{{when}}}\n    reply: {{text: {json.dumps(text)}}}\n"


async def test_the_default_entry_replays_the_s01_plan() -> None:
    reply = await ReplayProvider.s01(catalog_dir_from_env()).complete(["Crée Safe Eat"])
    assert [c.name for c in reply.tool_calls] == ["propose_plan"]
    plan = ProposePlanArguments.model_validate(reply.tool_calls[0].arguments)
    assert [
        (s.tool, (s.params or {}).get("path", (s.params or {}).get("playbook"))) for s in plan.steps
    ] == [
        ("gitlab.create_group", "safe-eat"),
        ("gitlab.create_group", "backend"),
        ("gitlab.create_group", "frontend"),
        ("gitlab.create_project", "safe-eat-api"),
        ("gitlab.create_project", "safe-eat-web"),
        ("server.apply_playbook", "bootstrap_project"),
        ("server.apply_playbook", "deploy_compose"),
    ]
    assert plan.environment == "staging"
    assert plan.skills == [
        "gitlab-project-creation",
        "go-backend-standard",
        "docker-staging-deploy",
    ]


async def test_replay_is_deterministic_and_stateless() -> None:
    provider = ReplayProvider.s01(catalog_dir_from_env())
    first = await provider.complete(["a"])
    second = await provider.complete(["autre message", "b"])
    assert first == second
    pristine = copy.deepcopy(second)
    first.tool_calls[0].arguments["steps"][0]["tool"] = "pirate"  # type: ignore[index]
    # Un appelant ne peut pas altérer les réponses suivantes.
    assert (await provider.complete(["a"])) == pristine


async def test_the_reply_is_chosen_on_the_sha256_of_the_last_message_only(tmp_path: Path) -> None:
    path = write_recording(
        tmp_path,
        exchange(f"last_user_sha256: {sha('bonjour')}", "salut")
        + exchange(f"last_user_sha256: {sha('merci')}", "de rien"),
    )
    provider = ReplayProvider(path)
    assert (await provider.complete(["merci", "bonjour"])).text == "salut"
    assert (await provider.complete(["bonjour", "merci"])).text == "de rien"


async def test_no_regex_and_no_near_match_selects_an_entry(tmp_path: Path) -> None:
    path = write_recording(tmp_path, exchange(f"last_user_sha256: {sha('bonjour')}", "salut"))
    provider = ReplayProvider(path)
    for message in ("Bonjour", "bonjour ", "bon.*", ".*", ""):
        with pytest.raises(RecordingNotFound):
            await provider.complete([message])
    with pytest.raises(RecordingNotFound):
        await provider.complete([])


async def test_a_specific_entry_wins_over_the_default(tmp_path: Path) -> None:
    path = write_recording(
        tmp_path,
        exchange("default: true", "par défaut")
        + exchange(f"last_user_sha256: {sha('x')}", "précis"),
    )
    provider = ReplayProvider(path)
    assert (await provider.complete(["x"])).text == "précis"
    assert (await provider.complete(["y"])).text == "par défaut"


async def test_a_missing_recording_is_a_typed_error_that_never_reaches_the_events(
    tmp_path: Path,
) -> None:
    provider = ReplayProvider(
        write_recording(tmp_path, exchange(f"last_user_sha256: {sha('connu')}", "ok"))
    )
    log = InMemoryEventLog()
    service = TurnService(provider, log)
    project_id = uuid4()
    request = TurnRequest(user_id="u", project_id=project_id, message="inconnu-secret-xyz")
    await service.run(request, service.begin(project_id))
    events = [e.model_dump(mode="json") for e in await log.read_after(project_id, 0)]
    assert [e["type"] for e in events] == ["message", "turn_status", "error", "turn_status"]
    assert events[2]["data"]["code"] == "internal_error"
    assert "RecordingNotFound" not in json.dumps(events[2:])


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("version: 2\nexchanges:\n" + exchange("default: true", "x"), id="version"),
        pytest.param("version: 1\nexchanges: []\n", id="empty"),
        pytest.param(
            "version: 1\nexchanges:\n" + exchange("default: false", "x"), id="no-selector"
        ),
        pytest.param(
            "version: 1\nexchanges:\n"
            + exchange(f"last_user_sha256: {sha('a')}, default: true", "x"),
            id="two-selectors",
        ),
        pytest.param(
            "version: 1\nexchanges:\n" + exchange("last_user_sha256: abc", "x"), id="short-hash"
        ),
        pytest.param(
            "version: 1\nexchanges:\n"
            + exchange("default: true", "x")
            + exchange("default: true", "y"),
            id="two-defaults",
        ),
        pytest.param(
            "version: 1\nexchanges:\n"
            + exchange(f"last_user_sha256: {sha('a')}", "x")
            + exchange(f"last_user_sha256: {sha('a')}", "y"),
            id="duplicate-hash",
        ),
        pytest.param(
            "version: 1\nexchanges: !!python/object/apply:os.getcwd []\n", id="unsafe-yaml"
        ),
        pytest.param("version: 1\nsurprise: 1\nexchanges: []\n", id="unknown-key"),
    ],
)
def test_an_invalid_recording_stops_the_startup(tmp_path: Path, content: str) -> None:
    path = tmp_path / "rec.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(RecordingInvalid):
        ReplayProvider(path)


def test_an_absent_recording_file_stops_the_startup(tmp_path: Path) -> None:
    with pytest.raises(RecordingInvalid):
        ReplayProvider(tmp_path / "absent.yaml")


async def test_an_entry_with_default_false_is_selected_by_its_hash(tmp_path: Path) -> None:
    path = write_recording(
        tmp_path,
        exchange(f"last_user_sha256: {sha('x')}, default: false", "précis")
        + exchange("default: true", "par défaut"),
    )
    provider = ReplayProvider(path)
    assert (await provider.complete(["x"])).text == "précis"


def test_a_symlinked_or_foreign_recording_is_refused(tmp_path: Path) -> None:
    real = write_recording(tmp_path, exchange("default: true", "x"))
    link = tmp_path / "link.yaml"
    link.symlink_to(real)
    with pytest.raises(RecordingInvalid):
        ReplayProvider(link)
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(RecordingInvalid):
        ReplayProvider(real, base=outside)


def test_an_invalid_recording_never_leaks_its_content(tmp_path: Path) -> None:
    secret = "jeton-glpat-ne-doit-pas-sortir"  # noqa: S105
    path = tmp_path / "rec.yaml"
    path.write_text(f"version: {secret}\nexchanges: []\n", encoding="utf-8")
    with pytest.raises(RecordingInvalid) as excinfo:
        ReplayProvider(path)
    assert secret not in "".join(traceback.format_exception(excinfo.value))
