from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from foreman.surfaces.web.app import create_app


def test_healthz() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "profile": "web"}


def test_serves_spa_when_static_dir_is_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "index.html").write_text("<h1>spa</h1>")
    monkeypatch.setenv("FOREMAN_STATIC_DIR", str(tmp_path))
    client = TestClient(create_app())
    assert client.get("/").text == "<h1>spa</h1>"
    assert client.get("/healthz").json()["status"] == "ok"
