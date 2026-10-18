import pytest

from foreman.config.env import ENV_ALLOW_DESTRUCTIVE_DOWNGRADE


@pytest.fixture(autouse=True)
def allow_destructive_downgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les bases de test sont jetables : le retour arrière peut supprimer l'audit."""
    monkeypatch.setenv(ENV_ALLOW_DESTRUCTIVE_DOWNGRADE, "1")
