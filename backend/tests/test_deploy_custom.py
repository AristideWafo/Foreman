"""Garde-fous du déploiement sur serveur Traefik (deploy-custom.sh, compose.custom.yaml)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
SCRIPT = DEPLOY / "deploy-custom.sh"
COMPOSE = DEPLOY / "compose.custom.yaml"
DIGEST = "sha256:" + "a" * 64
IMAGE = f"ghcr.io/aristidewafo/foreman@{DIGEST}"
AUTH = "admin:$apr1$sel$empreinte"  # empreinte factice (le `$` est littéral : pas de shell ici)


def run_script(*args: str, ssh_command: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"]}
    if ssh_command is not None:
        env["SSH_ORIGINAL_COMMAND"] = ssh_command
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    "args",
    [
        ("--dry-run", "Mauvais_Nom", IMAGE),
        ("--dry-run", "../etc", IMAGE),
        ("--dry-run", "mon-app", "ghcr.io/aristidewafo/foreman:latest"),
        ("--dry-run", "mon-app", f"docker.io/x/y@{DIGEST}"),
        ("--dry-run", "--rm", IMAGE),
        ("--dry-run",),
    ],
)
def test_rejects_untrusted_input(args: tuple[str, ...]) -> None:
    result = run_script(*args)
    assert result.returncode != 0
    assert "dry-run : rien" not in result.stdout


def test_ssh_forced_command_only_accepts_deploy() -> None:
    result = run_script(ssh_command="rm -rf /")
    assert result.returncode == 2
    assert "refusée" in result.stderr


def test_ssh_forced_command_validates_project() -> None:
    result = run_script(ssh_command=f"deploy 'x;id' {IMAGE}")
    assert result.returncode == 2


def test_single_argument_keeps_workflow_form() -> None:
    result = run_script("--dry-run", IMAGE)
    assert result.returncode == 0
    assert "projet      : foreman" in result.stdout
    assert "/opt/foreman" in result.stdout


def test_dry_run_with_project_and_db() -> None:
    result = run_script("--dry-run", "--with-db", "mon-app", IMAGE)
    assert result.returncode == 0
    assert "/opt/mon-app" in result.stdout
    assert "PostgreSQL  : oui" in result.stdout


@pytest.mark.skipif(
    shutil.which("docker") is None
    or subprocess.run(
        ["docker", "compose", "version"],  # noqa: S607
        capture_output=True,
        check=False,
    ).returncode
    != 0,
    reason="docker compose indisponible",
)
class TestRenderedCompose:
    @staticmethod
    def render(
        tmp_path: Path, *, profile: str = "", basic_auth: bool = True
    ) -> dict[str, dict[str, object]]:
        (tmp_path / "compose.yaml").write_text(COMPOSE.read_text())
        (tmp_path / ".env").write_text("")
        env = {
            "PATH": os.environ["PATH"],
            "PROJECT": "mon-app",
            "FOREMAN_IMAGE": IMAGE,
            "FOREMAN_DOMAIN": "mon-app.example.com",
            "COMPOSE_PROFILES": profile,
        }
        if basic_auth:  # retour arrière ; absent en mode session
            env["FOREMAN_BASIC_AUTH_USERS"] = AUTH
        if profile == "db":  # sans profil, POSTGRES_PASSWORD ne doit pas être exigé
            env.update({"POSTGRES_PASSWORD": "test"})
        out = subprocess.run(
            ["docker", "compose", "-f", "compose.yaml", "config", "--format", "json"],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return json.loads(out.stdout)

    def test_traefik_labels(self, tmp_path: Path) -> None:
        app = self.render(tmp_path)["services"]["app"]
        labels: dict[str, str] = app["labels"]
        assert labels["traefik.enable"] == "true"
        assert labels["traefik.http.routers.mon-app.rule"] == "Host(`mon-app.example.com`)"
        assert labels["traefik.http.routers.mon-app.tls"] == "true"
        assert labels["traefik.http.services.mon-app.loadbalancer.server.port"] == "8000"
        assert "mon-app-redirect" in labels["traefik.http.routers.mon-app-http.middlewares"]

    def test_every_service_has_limits_and_bounded_logs(self, tmp_path: Path) -> None:
        services = self.render(tmp_path, profile="db")["services"]
        assert set(services) == {"app", "db"}
        for name, service in services.items():
            limits = service["deploy"]["resources"]["limits"]
            assert {"cpus", "memory", "pids"} <= set(limits), name
            assert service["logging"]["options"]["max-size"], name

    def test_database_is_never_on_the_traefik_network(self, tmp_path: Path) -> None:
        services = self.render(tmp_path, profile="db")["services"]
        assert list(services["db"]["networks"]) == ["internal"]

    def test_app_is_hardened(self, tmp_path: Path) -> None:
        app = self.render(tmp_path)["services"]["app"]
        assert app["read_only"] is True
        assert app["cap_drop"] == ["ALL"]
        assert "ports" not in app

    def test_session_mode_attaches_no_basic_auth(self, tmp_path: Path) -> None:
        labels = self.render(tmp_path, basic_auth=False)["services"]["app"]["labels"]
        main = labels["traefik.http.routers.mon-app.middlewares"].split(",")
        assert main == ["mon-app-headers", "mon-app-compress"]
        assert labels["traefik.http.routers.mon-app-http.middlewares"] == "mon-app-redirect"

    def test_the_whole_site_is_behind_basic_auth_except_healthz(self, tmp_path: Path) -> None:
        labels = self.render(tmp_path)["services"]["app"]["labels"]
        # `docker compose config` réécrit `$` en `$$` à l'affichage (sortie ré-analysable) ;
        # la valeur réellement transmise à Traefik garde un seul `$`.
        users = labels["traefik.http.middlewares.mon-app-auth.basicauth.users"]
        assert users.replace("$$", "$") == AUTH
        assert labels["traefik.http.middlewares.mon-app-auth.basicauth.removeheader"] == "true"
        main = labels["traefik.http.routers.mon-app.middlewares"].split(",")
        assert main[0] == "mon-app-auth"  # l'authentification passe avant tout le reste
        health = labels["traefik.http.routers.mon-app-health.middlewares"].split(",")
        assert "mon-app-auth" not in health
        rule = labels["traefik.http.routers.mon-app-health.rule"]
        assert "Path(`/healthz`)" in rule
        assert int(labels["traefik.http.routers.mon-app-health.priority"]) > len(
            labels["traefik.http.routers.mon-app.rule"]
        )


STUB_DOCKER = r"""#!/usr/bin/env bash
# Faux docker : journalise chaque appel (profil compris) et simule la base selon des variables.
echo "profiles=${COMPOSE_PROFILES:-} $*" >> "$STUB_LOG"
case "$*" in
  "compose version --short") echo "${STUB_COMPOSE_VERSION:-2.29.0}" ;;
  *" ps --status running --services"*) [[ -n "${STUB_DB_RUNNING:-}" ]] && echo db ;;
  *" exec "*)
    echo "debut-de-dump"
    [[ -n "${STUB_DUMP_FAIL:-}" ]] && exit 1
    echo "fin-de-dump" ;;
esac
exit 0
"""


def stub_docker(tmp_path: Path, **extra: str) -> dict[str, str]:
    """Faux `docker` : permet d'exécuter le script sans serveur."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(STUB_DOCKER)
    docker.chmod(0o755)
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "DEPLOY_ROOT": str(tmp_path / "opt"),
        "STUB_LOG": str(tmp_path / "docker.log"),
        **extra,
    }


def run_deploy(tmp_path: Path, env_file: str) -> subprocess.CompletedProcess[str]:
    env = stub_docker(tmp_path)
    project_dir = tmp_path / "opt" / "mon-app"
    project_dir.mkdir(parents=True)
    (project_dir / ".env").write_text(env_file)
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "mon-app", IMAGE],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


BASE_ENV = "FOREMAN_DOMAIN=mon-app.example.com\n"


@pytest.mark.parametrize(
    "auth_line",
    [
        "",  # absent
        "FOREMAN_BASIC_AUTH_USERS=admin:motdepasseenclair\n",
        "FOREMAN_BASIC_AUTH_USERS=\n",
        "FOREMAN_BASIC_AUTH_USERS='admin:$apr1$sel$ok,bob:motdepasseenclair'\n",
    ],
)
def test_script_refuses_missing_or_plaintext_credentials(tmp_path: Path, auth_line: str) -> None:
    result = run_deploy(tmp_path, BASE_ENV + auth_line)
    assert result.returncode == 66
    assert "FOREMAN_BASIC_AUTH_USERS" in result.stderr
    assert not (tmp_path / "opt" / "mon-app" / ".current-image").exists()


@pytest.mark.parametrize(
    "auth_line",
    [
        "FOREMAN_BASIC_AUTH_USERS='admin:$apr1$sel$empreinte'\n",
        'FOREMAN_BASIC_AUTH_USERS="admin:$2y$05$abcdefghijklmnopqrstuv,bob:{SHA}abc="\n',
    ],
)
def test_script_accepts_hashed_credentials(tmp_path: Path, auth_line: str) -> None:
    result = run_deploy(tmp_path, BASE_ENV + auth_line)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "opt" / "mon-app" / ".current-image").read_text().strip() == IMAGE


SESSION_ENV = (
    BASE_ENV
    + "FOREMAN_AUTH_MODE=session\nFOREMAN_PUBLIC_URL=https://mon-app.example.com\n"
    + "FORWARDED_ALLOW_IPS=172.18.0.0/16\n"
)


def test_session_mode_needs_no_basic_auth(tmp_path: Path) -> None:
    result = run_deploy(tmp_path, SESSION_ENV)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "opt" / "mon-app" / ".current-image").exists()


@pytest.mark.parametrize(
    "replace",
    [
        ("FOREMAN_PUBLIC_URL=https://mon-app.example.com\n", ""),
        ("https://mon-app", "http://mon-app"),
        ("FORWARDED_ALLOW_IPS=172.18.0.0/16\n", ""),
        ("FORWARDED_ALLOW_IPS=172.18.0.0/16\n", "FORWARDED_ALLOW_IPS=*\n"),
        (
            "FORWARDED_ALLOW_IPS=172.18.0.0/16\n",
            "FORWARDED_ALLOW_IPS=172.18.0.0/16\nFOREMAN_COOKIE_SECURE=0\n",
        ),
        (
            "FORWARDED_ALLOW_IPS=172.18.0.0/16\n",
            "FORWARDED_ALLOW_IPS=172.18.0.0/16\nFOREMAN_BASIC_AUTH_USERS='a:$apr1$s$h'\n",
        ),
    ],
)
def test_session_mode_refuses_unsafe_config(tmp_path: Path, replace: tuple[str, str]) -> None:
    result = run_deploy(tmp_path, SESSION_ENV.replace(*replace))
    assert result.returncode == 66
    assert not (tmp_path / "opt" / "mon-app" / ".current-image").exists()


SECRET = "secretdetest"  # noqa: S105
AUTH_LINE = "FOREMAN_BASIC_AUTH_USERS='admin:$apr1$sel$empreinte'\n"
GOOD_URL = f"FOREMAN_DATABASE_URL=postgresql+psycopg://foreman:{SECRET}@db:5432/foreman\n"
DB_ENV = f"{BASE_ENV}{AUTH_LINE}POSTGRES_PASSWORD={SECRET}\n"


def run_deploy_with_db(
    tmp_path: Path, env_file: str, **stub: str
) -> subprocess.CompletedProcess[str]:
    env = stub_docker(tmp_path, **stub)
    project_dir = tmp_path / "opt" / "mon-app"
    project_dir.mkdir(parents=True)
    (project_dir / ".env").write_text(env_file)
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--with-db", "mon-app", IMAGE],  # noqa: S607
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    "url_lines",
    [
        "",  # absent : l'application retomberait en mémoire sans erreur
        "FOREMAN_DATABASE_URL=postgresql+psycopg://foreman:secretdetest@localhost:5432/foreman\n",
        "FOREMAN_DATABASE_URL=mysql://foreman:secretdetest@db:3306/foreman\n",
        "FOREMAN_DATABASE_URL=postgresql://foreman:secretdetest@evil.com@db:5432/foreman\n",
        "FOREMAN_DATABASE_URL=postgresql://foreman:secretdetest@db@evil.com:5432/foreman\n",
        "FOREMAN_DATABASE_URL=postgresql://foreman:secretdetest@db:5432/foreman?host=evil.com\n",
        # avec `%`, la comparaison à POSTGRES_* est sautée : seule la forme de l'URL protège
        "FOREMAN_DATABASE_URL=postgresql://foreman:p%41ss@evil.com@db:5432/foreman\n",
        "FOREMAN_DATABASE_URL=postgresql://foreman:p%41ss@db@evil.com:5432/foreman\n",
        "FOREMAN_DATABASE_URL=postgresql://foreman:p%41${H}@db:5432/foreman\n",
        # Compose et le script ne liraient pas le même fichier :
        GOOD_URL + "export FOREMAN_DATABASE_URL=postgresql://x:y@evil.com:5432/z\n",
        GOOD_URL + GOOD_URL,
        "  " + GOOD_URL,
        "export " + GOOD_URL,
        "FOREMAN_DATABASE_URL=postgresql://foreman:${H}@db:5432/foreman\n",
        # incohérent avec POSTGRES_* : la base ne s'ouvrirait jamais
        "FOREMAN_DATABASE_URL=postgresql://foreman:autremotdepasse@db:5432/foreman\n",
        f"FOREMAN_DATABASE_URL=postgresql://admin:{SECRET}@db:5432/foreman\n",
        f"FOREMAN_DATABASE_URL=postgresql://foreman:{SECRET}@db:5432/autre\n",
    ],
)
def test_with_db_refuses_unsafe_database_url(tmp_path: Path, url_lines: str) -> None:
    result = run_deploy_with_db(tmp_path, DB_ENV + url_lines)
    assert result.returncode == 66
    assert "FOREMAN_DATABASE_URL" in result.stderr
    assert SECRET not in result.stderr + result.stdout
    assert not result.stderr.rstrip().endswith(" 66")  # le code de sortie n'est pas dans le message
    assert not (tmp_path / "opt" / "mon-app" / ".current-image").exists()


def test_with_db_activates_profile_and_never_prints_the_url(tmp_path: Path) -> None:
    result = run_deploy_with_db(tmp_path, DB_ENV + GOOD_URL)
    assert result.returncode == 0, result.stderr
    assert SECRET not in result.stderr + result.stdout
    up = [x for x in (tmp_path / "docker.log").read_text().splitlines() if " up " in x]
    assert up
    assert all(x.startswith("profiles=db ") for x in up)


def test_without_db_flag_the_profile_stays_off(tmp_path: Path) -> None:
    result = run_deploy(tmp_path, BASE_ENV + AUTH_LINE)
    assert result.returncode == 0, result.stderr
    assert "profiles= " in (tmp_path / "docker.log").read_text()


def test_old_compose_is_refused(tmp_path: Path) -> None:
    result = run_deploy_with_db(tmp_path, DB_ENV + GOOD_URL, STUB_COMPOSE_VERSION="2.28.1")
    assert result.returncode == 69
    assert "2.29" in result.stderr


def backups(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "opt" / "backups").glob("*"))


def test_database_is_dumped_before_up_and_only_last_five_kept(tmp_path: Path) -> None:
    backup_dir = tmp_path / "opt" / "backups"
    backup_dir.mkdir(parents=True)
    for n in range(7):  # anciens dumps : 01 (le plus ancien) à 07
        dump = backup_dir / f"mon-app-2020010{n + 1}-000000.dump"
        dump.write_text("ancien")
        os.utime(dump, (1_000_000 + n, 1_000_000 + n))
    result = run_deploy_with_db(tmp_path, DB_ENV + GOOD_URL, STUB_DB_RUNNING="1")
    assert result.returncode == 0, result.stderr
    kept = backups(tmp_path)
    assert len(kept) == 5
    assert not (backup_dir / "mon-app-20200101-000000.dump").exists()
    new = [p for p in kept if not p.name.startswith("mon-app-2020")]
    assert len(new) == 1
    assert new[0].read_text() == "debut-de-dump\nfin-de-dump\n"
    assert new[0].stat().st_mode & 0o777 == 0o600
    assert backup_dir.stat().st_mode & 0o777 == 0o700
    log = (tmp_path / "docker.log").read_text().splitlines()
    assert next(i for i, x in enumerate(log) if " exec " in x) < next(
        i for i, x in enumerate(log) if " up " in x
    )
    assert SECRET not in "".join(log)  # aucun mot de passe en ligne de commande


def test_failed_dump_aborts_the_deployment_and_keeps_no_partial_file(tmp_path: Path) -> None:
    result = run_deploy_with_db(
        tmp_path, DB_ENV + GOOD_URL, STUB_DB_RUNNING="1", STUB_DUMP_FAIL="1"
    )
    assert result.returncode == 70
    assert backups(tmp_path) == []
    assert not (tmp_path / "opt" / "mon-app" / ".current-image").exists()
    assert " up " not in (tmp_path / "docker.log").read_text()


def test_first_deployment_has_nothing_to_dump(tmp_path: Path) -> None:
    result = run_deploy_with_db(tmp_path, DB_ENV + GOOD_URL)  # db ne tourne pas encore
    assert result.returncode == 0, result.stderr
    assert " exec " not in (tmp_path / "docker.log").read_text()


def test_dry_run_is_honoured_through_ssh_original_command() -> None:
    result = run_script(ssh_command=f"deploy --dry-run {IMAGE}")
    assert result.returncode == 0
    assert "dry-run : rien" in result.stdout
