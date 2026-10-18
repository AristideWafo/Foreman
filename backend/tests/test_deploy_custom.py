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
    def render(tmp_path: Path, *, profile: str = "") -> dict[str, dict[str, object]]:
        (tmp_path / "compose.yaml").write_text(COMPOSE.read_text())
        (tmp_path / ".env").write_text("")
        env = {
            "PATH": os.environ["PATH"],
            "PROJECT": "mon-app",
            "FOREMAN_IMAGE": IMAGE,
            "FOREMAN_DOMAIN": "mon-app.example.com",
            "POSTGRES_PASSWORD": "test",
            "FOREMAN_BASIC_AUTH_USERS": AUTH,
            "COMPOSE_PROFILES": profile,
        }
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

    def test_deployment_is_refused_without_credentials(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(COMPOSE.read_text())
        (tmp_path / ".env").write_text("")
        env = {
            "PATH": os.environ["PATH"],
            "PROJECT": "mon-app",
            "FOREMAN_IMAGE": IMAGE,
            "FOREMAN_DOMAIN": "mon-app.example.com",
            # seule FOREMAN_BASIC_AUTH_USERS manque : Compose interpole aussi db (profil inactif)
            "POSTGRES_PASSWORD": "x",
        }
        result = subprocess.run(
            ["docker", "compose", "-f", "compose.yaml", "config", "-q"],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert result.returncode != 0
        assert "FOREMAN_BASIC_AUTH_USERS" in result.stderr


def stub_docker(tmp_path: Path) -> dict[str, str]:
    """Faux `docker` qui accepte tout : permet d'exécuter le script sans serveur."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n")
    docker.chmod(0o755)
    return {"PATH": f"{bin_dir}:{os.environ['PATH']}", "DEPLOY_ROOT": str(tmp_path / "opt")}


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
