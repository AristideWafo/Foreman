"""Filtrage de ce qui sort d'un outil : masquage des secrets et bornes de taille.

Appliqué à la sortie, aux logs et aux paramètres journalisés, AVANT tout événement et tout audit.
Le masquage est une défense en profondeur (motifs connus et noms de champs sensibles), pas une
garantie : un outil ne doit pas renvoyer de secret, et déclare `redact` pour ses champs sensibles.

Ce code tourne SYNCHRONE dans la boucle asynchrone, sur des données que l'adaptateur contrôle :
tout motif est donc borné (quantificateurs bornés ou possessifs, ancrage sur un début de mot) et
le volume traité l'est aussi (texte, lignes, nœuds, clés). Dès qu'une limite est atteinte, le
reste est COMPTÉ mais plus traité. Le test de performance du dépôt vérifie que le temps de chaque
motif de `ALL_PATTERNS` croît linéairement.

Limites connues (formes non couvertes) : valeur sur la ligne SUIVANTE d'un `password:` YAML,
`!vault`, DSN `user:pw@tcp(...)`, `.netrc`, en-têtes `Cookie` à plusieurs cookies, deux-points
pleine chasse, clés PuTTY, secrets en base64, mot de passe contenant `/` non encodé dans une URL.
"""

import json
import re
from collections.abc import Iterable, Mapping
from typing import Final

from pydantic import JsonValue

MASK: Final = "[masqué]"
MAX_OUTPUT_BYTES: Final = 4 * 1024
OMISSION_RESERVE_BYTES: Final = 64  # place réservée à la ligne « … N ligne(s) omise(s) »
MAX_LOG_LINES: Final = 50
MAX_LINE_CHARS: Final = 500
PRE_MASK_CHARS: Final = 4 * MAX_LINE_CHARS  # texte masqué : jamais plus
SCAN_CHARS: Final = 64 * 1024  # recherche des marqueurs de bloc (clé privée) dans une ligne
MAX_NODES: Final = 1_000  # nœuds et clés traités par sortie
MAX_VALUE_CHARS: Final = 32 * 1024  # caractères masqués par sortie
MAX_STRING_LINES: Final = 100
MAX_DEPTH: Final = 8
_ELLIPSIS: Final = "…"

_WORDS: Final = (
    r"pass(?:word|wd)?|pwd|secret|token|api[_-]?key|private[_-]?key|credential|auth|cookie|"
    r"session|access[_-]?key|ssh[_-]?key"
)
# Nom contenant un mot sensible : au plus 80 caractères avant et après, ancré sur un début de nom.
_NAME: Final = rf"[\w.\-]{{0,80}}(?:{_WORDS})[\w.\-]{{0,80}}"
# Valeur : entre guillemets (espaces et guillemets échappés compris), guillemet jamais fermé, ou
# jusqu'au prochain blanc, guillemet ou virgule.
_VALUE: Final = (
    r"(?:\"(?:[^\"\\\r\n]|\\.){0,500}\"|'[^'\r\n]{0,500}'|[\"'][^\r\n]{0,500}+|[^\s\"',]++)"
)
_PEM_TYPE: Final = r"[A-Z ]{0,30}PRIVATE KEY(?: BLOCK)?"
_PEM_BEGIN: Final = re.compile(rf"-----BEGIN {_PEM_TYPE}-----")
_PEM_END: Final = re.compile(rf"-----END {_PEM_TYPE}-----")
_SENSITIVE_KEY: Final = re.compile(_WORDS, re.IGNORECASE)
_YAML_BLOCK: Final = re.compile(
    rf"[ \t]{{0,40}}-?[ \t]{{0,3}}{_NAME}[ \t]{{0,3}}:[ \t]{{0,3}}[>|][+\-0-9]{{0,2}}[ \t]*",
    re.IGNORECASE,
)
# Identifiants d'une URL : seulement dans la partie autorité (avant le premier `/`, `?` ou `#`).
URL_USERINFO: Final = re.compile(r"(\b[a-z][a-z0-9+.\-]{0,20}://)[^\s/?#]{0,512}@", re.IGNORECASE)

# Tous les motifs de masquage (hors URL, traitée à part) : le test de performance les parcourt.
PATTERNS: Final = tuple(
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in (
        rf"-----BEGIN {_PEM_TYPE}-----.*?(?:-----END {_PEM_TYPE}-----|$)",
        r"\bAuthorization[ \t]{0,20}[:=][^\r\n]*+",  # en-tête complet
        r"\bBasic[ \t]{1,20}[A-Za-z0-9+/=]{8,}+",
        r"\bBearer[ \t]{1,20}[A-Za-z0-9._~+/=\-]{8,}+",
        # Jetons à préfixe : sensibles à la casse (un nom de dépôt ne doit pas être masqué).
        r"(?-i:\bgithub_pat_[A-Za-z0-9_]{20,}+)",
        r"(?-i:\bgl(?:pat|ptt|rt|rtr|cbt|dt|ft|imt|oas|soat|agent|ffct|wt)-[A-Za-z0-9_\-]{20,}+)",
        r"(?-i:\bgh[pousr]_[A-Za-z0-9]{20,}+)",  # jetons GitHub
        r"(?-i:\bAKIA[0-9A-Z]{16}\b)",  # clé d'accès AWS
        r"(?-i:\bxox[abprs]-[A-Za-z0-9\-]{10,}+)",  # jetons Slack
        r"(?-i:\bsk-(?:(?:ant|proj|svcacct|admin)-[A-Za-z0-9_\-]{20,}+|[A-Za-z0-9_]{20,}+))",
        r"\beyJ[A-Za-z0-9_\-]{5,256}\.[A-Za-z0-9_\-]{5,256}\.[A-Za-z0-9_\-]{5,}+",  # JWT
        r"\b(?:docker|podman|helm)(?: registry)?[ \t]{1,5}login\b[^\r\n]{0,500}+",
        r"(?<![\w\-])(?:-u|--user)[ \t=]{1,5}[^\s:]{1,100}:\S{1,200}",  # -u utilisateur:secret
        # clé=valeur ou clé: valeur, noms composés compris (POSTGRES_PASSWORD, X_TOKEN, "token":)
        rf"(?<![\w.\-]){_NAME}[\"']?\s{{0,40}}[=:]\s{{0,20}}{_VALUE}",
        # -pMOT_DE_PASSE collé, pour les clients qui l'utilisent (mysql, psql, sshpass...)
        r"\b(?:mysql|mysqldump|mariadb|psql|sshpass)\b[^\r\n]{0,200}?[ \t]-p[ \t]?\S{1,100}",
        # nom composé suivi d'une valeur sans séparateur : --password v, MYSQL_ROOT_PASSWORD v
        rf"(?<![\w.\-])(?=[\w.\-]{{0,80}}[_\-]){_NAME}[ \t]{{1,20}}(?![=:\-]){_VALUE}",
    )
)
ALL_PATTERNS: Final = (URL_USERINFO, *PATTERNS)


def mask_text(text: str) -> str:
    """Remplace chaque motif de secret connu par `MASK` (le schéma et l'hôte d'une URL restent).

    Le texte est borné avant d'être traité.
    """
    text = URL_USERINFO.sub(rf"\1{MASK}@", text[:PRE_MASK_CHARS])
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
        begins = list(_PEM_BEGIN.finditer(scanned))
        if begins:
            # Une clé reste ouverte si le DERNIER marqueur BEGIN n'est pas suivi de son END.
            self._in_key = _PEM_END.search(scanned, begins[-1].end()) is None
        elif _YAML_BLOCK.fullmatch(head):
            self._block_indent = len(raw) - len(raw.lstrip(" \t"))
        return _clip(mask_text(head))


def filter_logs(lines: Iterable[str]) -> list[str]:
    """Au plus `MAX_LOG_LINES` lignes de `MAX_LINE_CHARS` caractères, au plus 4 Kio au total, la
    ligne « … N ligne(s) omise(s) » comprise.

    Dès qu'une ligne ne tient pas, les suivantes sont seulement COMPTÉES (aucun masquage).
    """
    kept: list[str] = []
    total = 0
    omitted = 0
    full = False
    masker = _Masker()
    for raw in lines:
        if full:
            omitted += 1
            continue
        if len(kept) >= MAX_LOG_LINES - 1:
            full = True
            omitted += 1
            continue
        line = masker.line(raw)
        size = len(line.encode("utf-8")) + 1
        if total + size > MAX_OUTPUT_BYTES - OMISSION_RESERVE_BYTES:
            full = True
            omitted += 1
            continue
        kept.append(line)
        total += size
    if omitted:
        kept.append(f"… {omitted} ligne(s) omise(s)")
    return kept


class _State:
    """Ce qu'une sortie a le droit de faire traiter (nœuds, clés, caractères) et le masqueur
    UNIQUE de l'appel : un bloc ouvert dans un champ se referme dans le suivant."""

    def __init__(self) -> None:
        self.nodes = MAX_NODES
        self.chars = MAX_VALUE_CHARS
        self.masker = _Masker()

    @property
    def exhausted(self) -> bool:
        return self.nodes <= 0 or self.chars <= 0


def _mask_string(text: str, state: _State) -> str:
    """Chaîne multi-lignes masquée ligne à ligne (état conservé), puis tronquée."""
    lines = text[: PRE_MASK_CHARS * 4].split("\n")[:MAX_STRING_LINES]
    out: list[str] = []
    for line in lines:
        state.chars -= min(len(line), PRE_MASK_CHARS)
        out.append(state.masker.line(line) if state.chars >= 0 else MASK)
    return _clip("\n".join(out))


def _unique(name: str, taken: Mapping[str, object]) -> str:
    """Deux clés qui se masquent pareil ne doivent pas s'écraser."""
    if name not in taken:
        return name
    n = 2
    while f"{name}#{n}" in taken:
        n += 1
    return f"{name}#{n}"


def redact_value(
    value: JsonValue, fields: frozenset[str], _state: _State | None = None, _depth: int = 0
) -> JsonValue:
    """Masque les champs déclarés (`fields`) ou au nom sensible, et les motifs de secret.

    Les chaînes sont tronquées à `MAX_LINE_CHARS`, les noms de clé masqués comme les valeurs (sur
    `MAX_LINE_CHARS` caractères). Au-delà de `MAX_DEPTH`, de `MAX_NODES` nœuds ou clés, ou de
    `MAX_VALUE_CHARS` caractères, le reste est abandonné (clé `truncated`, élément masqué).
    """
    state = _state or _State()
    state.nodes -= 1
    if _depth > MAX_DEPTH or state.nodes < 0:
        return MASK
    if isinstance(value, str):
        return _mask_string(value, state)
    if isinstance(value, dict):
        out: dict[str, JsonValue] = {}
        for key, item in value.items():
            if state.exhausted:
                out["truncated"] = True
                break
            state.nodes -= 1
            state.chars -= min(len(key), MAX_LINE_CHARS)
            short = key[:MAX_LINE_CHARS]
            name = _unique(_clip(mask_text(short)), out)
            hidden = key in fields or _SENSITIVE_KEY.search(short)
            out[name] = MASK if hidden else redact_value(item, fields, state, _depth + 1)
        return out
    if isinstance(value, list | tuple):
        items: list[JsonValue] = []
        for item in value:
            if state.exhausted:
                items.append(MASK)
                break
            items.append(redact_value(item, fields, state, _depth + 1))
        return items
    return value


def strip_paths(output: dict[str, JsonValue], paths: Iterable[str]) -> dict[str, JsonValue]:
    """Retire de `output` (déjà copié par `redact_value`) les chemins `a.b[*].c` : le champ est
    absent, pas masqué. Un chemin sans correspondance ne fait rien."""
    for path in paths:
        _strip(output, path.split("."))
    return output


def _strip(node: JsonValue, segments: list[str]) -> None:
    head, *rest = segments
    each = head.endswith("[*]")
    key = head[:-3] if each else head
    if not isinstance(node, dict) or key not in node:
        return
    if not rest:
        del node[key]
        return
    child = node[key]
    for item in child if each and isinstance(child, list) else [child]:
        _strip(item, rest)


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


def truncated_output(masked: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """Sortie déjà masquée mais trop grande : `truncated` plus les valeurs scalaires courtes qui
    tiennent (les identifiants dont les étapes suivantes ont besoin) ; le reste est abandonné.
    Ne masque rien de plus : le travail a déjà été payé."""
    result: dict[str, JsonValue] = {"truncated": True}
    for key, item in masked.items():
        if isinstance(item, dict | list):
            continue
        if json_size({**result, key: item}) <= MAX_OUTPUT_BYTES:
            result[key] = item
    return result
