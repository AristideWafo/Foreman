"""Enregistrements de vraies réponses du modèle (`catalog/recordings/real/*.json`).

Un enregistrement garde la réponse brute de l'API Messages (JSON `Message`) et l'usage, APRÈS
masquage par `redact.mask_text`. Un enregistrement qui contient encore un motif de secret, ou une
chaîne trop longue pour être masquée entièrement, est refusé en écriture comme en lecture.
"""

import json
import re
from pathlib import Path
from typing import Any, Final

from foreman.core.gateway.redact import PRE_MASK_CHARS, mask_text

REAL_DIR: Final = Path("recordings") / "real"
VERSION: Final = 1
_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class RecordingRefused(Exception):
    """Enregistrement refusé (motif de secret, forme invalide). Message fixe, sans contenu."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"enregistrement refusé : {reason}")


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > PRE_MASK_CHARS:
            raise RecordingRefused("chaîne trop longue pour être masquée")
        return mask_text(value)
    if isinstance(value, list):
        return [_mask(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    return value


def ensure_clean(recording: dict[str, Any]) -> None:
    """Refuse un enregistrement que le masquage modifierait (motif de secret présent)."""
    if _mask(recording) != recording:
        raise RecordingRefused("motif de secret détecté")


def build_recording(
    model: str, message: dict[str, Any], *, last_user_sha256: str, synthetic: bool = False
) -> dict[str, Any]:
    """Recording masqué à partir du JSON `Message` brut. Lève `RecordingRefused`."""
    usage = message.get("usage")
    if not isinstance(usage, dict) or not isinstance(usage.get("input_tokens"), int):
        raise RecordingRefused("usage absent")
    recording = _mask(
        {
            "version": VERSION,
            "synthetic": synthetic,
            "model": model,
            "last_user_sha256": last_user_sha256,
            "message": message,
            "usage": {
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_input_tokens") or 0,
                "cache_write_tokens": usage.get("cache_creation_input_tokens") or 0,
            },
        }
    )
    ensure_clean(recording)
    return recording  # type: ignore[no-any-return]


def write_recording(catalog_dir: Path, name: str, recording: dict[str, Any]) -> Path:
    if not _NAME.fullmatch(name):
        raise RecordingRefused("nom invalide")
    ensure_clean(recording)
    folder = catalog_dir / REAL_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps(recording, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_recording(path: Path) -> dict[str, Any]:
    try:
        recording = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RecordingRefused("fichier illisible") from None
    if not isinstance(recording, dict) or recording.get("version") != VERSION:
        raise RecordingRefused("version inconnue")
    ensure_clean(recording)
    return recording
