"""Filtrage de ce qui sort d'un outil : masquage des secrets et bornes de taille.

Appliqué à la sortie, aux logs et aux paramètres journalisés, AVANT tout événement et tout audit.
Le masquage est une défense en profondeur (motifs connus et noms de champs sensibles), pas une
garantie : un outil ne doit pas renvoyer de secret, et déclare `redact` pour ses champs sensibles.
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Final

from pydantic import JsonValue

MASK: Final = "[masqué]"
MAX_OUTPUT_BYTES: Final = 4 * 1024
MAX_LOG_LINES: Final = 50
MAX_LINE_CHARS: Final = 500
MAX_DEPTH: Final = 8
_ELLIPSIS: Final = "…"

# Noms de champs masqués quelle que soit la déclaration `redact` de l'outil.
_SENSITIVE_KEY: Final = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|authorization|private[_-]?key|credential",
    re.IGNORECASE,
)
_SECRET_PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
        r"\bgl(?:pat|ptt|rt|dt)-[A-Za-z0-9_\-]{10,}",  # jetons GitLab
        r"\bgh[pousr]_[A-Za-z0-9]{20,}",  # jetons GitHub
        r"\bAKIA[0-9A-Z]{16}\b",  # clé d'accès AWS
        r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",  # jetons Slack
        r"\bsk-[A-Za-z0-9_\-]{20,}",  # clés d'API de type sk-...
        r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}",  # JWT
        r"\bBearer\s+[A-Za-z0-9._~+/=\-]{8,}",
        r"://[^/\s:@]+:[^/\s@]+@",  # identifiants dans une URL
        r"\b(?:pass(?:word|wd)?|secret|token|api[_-]?key)\b\s*[=:]\s*\S+",  # clé=valeur
    )
)


def mask_text(text: str) -> str:
    """Remplace chaque motif de secret connu par `MASK`."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 1] + _ELLIPSIS


def filter_logs(lines: Iterable[str]) -> list[str]:
    """Au plus `MAX_LOG_LINES` lignes de `MAX_LINE_CHARS` caractères, au plus 4 Kio au total."""
    kept: list[str] = []
    total = 0
    omitted = 0
    for raw in lines:
        line = _clip(mask_text(raw).replace("\r", " ").replace("\n", " "))
        size = len(line.encode("utf-8")) + 1
        if len(kept) >= MAX_LOG_LINES - 1 or total + size > MAX_OUTPUT_BYTES:
            omitted += 1
            continue
        kept.append(line)
        total += size
    if omitted:
        kept.append(f"… {omitted} ligne(s) omise(s)")
    return kept


def redact_value(value: JsonValue, fields: frozenset[str], _depth: int = 0) -> JsonValue:
    """Masque les champs déclarés (`fields`) ou au nom sensible, et les motifs de secret.

    Les chaînes sont tronquées à `MAX_LINE_CHARS`. Au-delà de `MAX_DEPTH`, la valeur est masquée.
    """
    if _depth > MAX_DEPTH:
        return MASK
    if isinstance(value, str):
        return _clip(mask_text(value))
    if isinstance(value, dict):
        return {
            key: MASK
            if key in fields or _SENSITIVE_KEY.search(key)
            else redact_value(item, fields, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, fields, _depth + 1) for item in value]
    return value


def json_size(value: Mapping[str, JsonValue]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def bounded_for_audit(
    value: Mapping[str, JsonValue], fields: frozenset[str]
) -> dict[str, JsonValue]:
    """Version masquée et bornée (4 Kio) destinée à l'audit."""
    redacted = redact_value(dict(value), fields)
    assert isinstance(redacted, dict)  # noqa: S101 - `redact_value` d'un dict rend un dict
    if json_size(redacted) > MAX_OUTPUT_BYTES:
        return {"truncated": True}
    return redacted
