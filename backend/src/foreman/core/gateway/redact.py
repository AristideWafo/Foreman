"""Filtrage de ce qui sort d'un outil : masquage des secrets et bornes de taille.

Appliqué à la sortie, aux logs et aux paramètres journalisés, AVANT tout événement et tout audit.
Le masquage est une défense en profondeur (motifs connus et noms de champs sensibles), pas une
garantie : un outil ne doit pas renvoyer de secret, et déclare `redact` pour ses champs sensibles.

Ce code tourne SYNCHRONE dans la boucle asynchrone, sur des données que l'adaptateur contrôle :
tout motif est donc borné (quantificateurs bornés ou possessifs, ancrage sur un début de mot) et
le volume traité l'est aussi (texte, lignes, nœuds). Le test de performance du dépôt applique
chaque motif de `PATTERNS` à des entrées pathologiques de 100 Ko.
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
PRE_MASK_CHARS: Final = 4 * MAX_LINE_CHARS  # texte masqué : jamais plus
SCAN_CHARS: Final = 64 * 1024  # recherche des marqueurs de bloc (clé privée) dans une ligne
MAX_NODES: Final = 1_000  # nœuds JSON traités par sortie
MAX_VALUE_CHARS: Final = 32 * 1024  # caractères masqués par sortie
MAX_STRING_LINES: Final = 100
MAX_DEPTH: Final = 8
_ELLIPSIS: Final = "…"

_WORDS: Final = (
    r"pass(?:word|wd)?|pwd|secret|token|api[_-]?key|private[_-]?key|credential|auth|cookie|"
    r"session|access[_-]?key|ssh[_-]?key"
)
# Nom contenant un mot sensible : au plus 40 caractères avant et après, ancré sur un début de nom.
_NAME: Final = rf"[\w.\-]{{0,40}}(?:{_WORDS})[\w.\-]{{0,40}}"
_PEM_TYPE: Final = r"[A-Z ]{0,30}PRIVATE KEY(?: BLOCK)?"
_PEM_BEGIN: Final = re.compile(rf"-----BEGIN {_PEM_TYPE}-----")
_PEM_END: Final = re.compile(rf"-----END {_PEM_TYPE}-----")
_SENSITIVE_KEY: Final = re.compile(_WORDS, re.IGNORECASE)
_YAML_BLOCK: Final = re.compile(
    rf"[ \t]{{0,40}}-?[ \t]{{0,3}}{_NAME}[ \t]{{0,3}}:[ \t]{{0,3}}[>|][+\-0-9]{{0,2}}[ \t]*",
    re.IGNORECASE,
)
_URL_USERINFO: Final = re.compile(r"(\b[a-z][a-z0-9+.\-]{0,20}://)\S{0,128}@", re.IGNORECASE)

# Tous les motifs de masquage (hors URL, traitée à part) : le test de performance les parcourt.
PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        rf"-----BEGIN {_PEM_TYPE}-----.*?(?:-----END {_PEM_TYPE}-----|$)",
        r"\bAuthorization[ \t]{0,20}[:=][^\r\n]*+",  # en-tête complet
        r"\bBasic[ \t]{1,20}[A-Za-z0-9+/=]{8,}+",
        r"\bBearer[ \t]{1,20}[A-Za-z0-9._~+/=\-]{8,}+",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}+",
        r"\bgl[a-z]{2,5}-[A-Za-z0-9_\-]{10,}+",  # glpat-, glptt-, glrt-, glcbt-, gldt-...
        r"\bgh[pousr]_[A-Za-z0-9]{20,}+",  # jetons GitHub
        r"\bAKIA[0-9A-Z]{16}\b",  # clé d'accès AWS
        r"\bxox[abprs]-[A-Za-z0-9\-]{10,}+",  # jetons Slack
        r"\bsk-[A-Za-z0-9_\-]{20,}+",  # clés d'API de type sk-...
        r"\beyJ[A-Za-z0-9_\-]{5,256}\.[A-Za-z0-9_\-]{5,256}\.[A-Za-z0-9_\-]{5,}+",  # JWT
        # clé=valeur ou clé: valeur, noms composés compris (POSTGRES_PASSWORD, X_TOKEN, "token":)
        rf"(?<![\w.\-]){_NAME}[\"']?\s{{0,20}}[=:]\s{{0,20}}[\"']?[^\s\"',;]++",
        r"(?<![\w\-])-p(?=[^\s\-])[^\s\"',;]++",  # -psecret (mysql)
        # nom composé suivi d'une valeur sans séparateur : --password v, MYSQL_ROOT_PASSWORD v
        rf"(?<![\w.\-])(?=[\w.\-]{{0,80}}[_\-]){_NAME}[ \t]{{1,20}}(?![=:\-])[^\s\"',;]++",
    )
)


def mask_text(text: str) -> str:
    """Remplace chaque motif de secret connu par `MASK` (le schéma et l'hôte d'une URL restent).

    Le texte est borné avant d'être traité.
    """
    text = _URL_USERINFO.sub(rf"\1{MASK}@", text[:PRE_MASK_CHARS])
    for pattern in PATTERNS:
        text = pattern.sub(MASK, text)
    return text


def _clip(text: str) -> str:
    return text if len(text) <= MAX_LINE_CHARS else text[: MAX_LINE_CHARS - 1] + _ELLIPSIS


class _Masker:
    """Masque des lignes successives en gardant l'état des blocs qui s'étendent sur plusieurs
    lignes : clé privée (de BEGIN à END, même si BEGIN dépasse le texte conservé) et bloc YAML
    `clé: >-` dont le corps est indenté."""

    def __init__(self) -> None:
        self._in_key = False
        self._block_indent: int | None = None

    def line(self, raw: str) -> str:
        head = raw[:PRE_MASK_CHARS].replace("\r", " ").replace("\n", " ")
        scanned = raw[:SCAN_CHARS]
        if self._in_key:
            self._in_key = _PEM_END.search(scanned) is None
            return MASK
        if self._block_indent is not None:
            indent = len(raw) - len(raw.lstrip(" \t"))
            if not raw.strip() or indent > self._block_indent:
                return MASK
            self._block_indent = None
        begin = _PEM_BEGIN.search(scanned)
        if begin is not None:
            self._in_key = _PEM_END.search(scanned, begin.end()) is None
        elif _YAML_BLOCK.fullmatch(head):
            self._block_indent = len(raw) - len(raw.lstrip(" \t"))
        return _clip(mask_text(head))


def filter_logs(lines: Iterable[str]) -> list[str]:
    """Au plus `MAX_LOG_LINES` lignes de `MAX_LINE_CHARS` caractères, au plus 4 Kio au total.

    Une fois la limite atteinte, les lignes suivantes ne sont plus traitées (seulement comptées).
    """
    kept: list[str] = []
    total = 0
    omitted = 0
    masker = _Masker()
    for raw in lines:
        if len(kept) >= MAX_LOG_LINES - 1 or total >= MAX_OUTPUT_BYTES:
            omitted += 1
            continue
        line = masker.line(raw)
        size = len(line.encode("utf-8")) + 1
        if total + size > MAX_OUTPUT_BYTES:
            omitted += 1
            continue
        kept.append(line)
        total += size
    if omitted:
        kept.append(f"… {omitted} ligne(s) omise(s)")
    return kept


class _Budget:
    """Volume qu'une sortie a le droit de faire traiter : nœuds et caractères."""

    def __init__(self) -> None:
        self.nodes = MAX_NODES
        self.chars = MAX_VALUE_CHARS


def _mask_string(text: str, budget: _Budget, masker: _Masker | None = None) -> str:
    """Chaîne multi-lignes masquée ligne à ligne (état conservé), puis tronquée."""
    masker = masker or _Masker()
    lines = text[: PRE_MASK_CHARS * 4].split("\n")[:MAX_STRING_LINES]
    out: list[str] = []
    for line in lines:
        budget.chars -= min(len(line), PRE_MASK_CHARS)
        out.append(masker.line(line) if budget.chars >= 0 else MASK)
    return _clip("\n".join(out))


def redact_value(
    value: JsonValue, fields: frozenset[str], _budget: _Budget | None = None, _depth: int = 0
) -> JsonValue:
    """Masque les champs déclarés (`fields`) ou au nom sensible, et les motifs de secret.

    Les chaînes sont tronquées à `MAX_LINE_CHARS`, les noms de clé masqués comme les valeurs, une
    liste de chaînes est traitée d'une traite (une clé privée découpée en éléments est masquée).
    Au-delà de `MAX_DEPTH` ou de `MAX_NODES` nœuds, la valeur est masquée.
    """
    budget = _budget or _Budget()
    budget.nodes -= 1
    if _depth > MAX_DEPTH or budget.nodes < 0:
        return MASK
    if isinstance(value, str):
        return _mask_string(value, budget)
    if isinstance(value, dict):
        return {
            _clip(mask_text(key)): MASK
            if key in fields or _SENSITIVE_KEY.search(key)
            else redact_value(item, fields, budget, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            masker = _Masker()
            out: list[JsonValue] = []
            for item in value:
                budget.nodes -= 1
                out.append(MASK if budget.nodes < 0 else _mask_string(str(item), budget, masker))
            return out
        return [redact_value(item, fields, budget, _depth + 1) for item in value]
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


def truncated_output(
    value: Mapping[str, JsonValue], fields: frozenset[str]
) -> dict[str, JsonValue]:
    """Sortie trop grande : `truncated` plus les valeurs scalaires courtes qui tiennent (les
    identifiants dont les étapes suivantes ont besoin) ; le reste est abandonné."""
    result: dict[str, JsonValue] = {"truncated": True}
    for key, item in list(value.items())[:MAX_NODES]:
        if isinstance(item, dict | list):
            continue
        masked = redact_value({key: item}, fields)
        assert isinstance(masked, dict)  # noqa: S101 - `redact_value` d'un dict rend un dict
        if json_size({**result, **masked}) <= MAX_OUTPUT_BYTES:
            result.update(masked)
    return result
