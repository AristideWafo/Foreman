"""Références entre étapes : `{"$from": {"step": N, "field": "nom"}}`.

Un paramètre d'étape peut désigner un champ de la sortie d'une étape ANTÉRIEURE (par exemple
l'identifiant du groupe créé). La résolution est pure et fermée : seule la forme exacte ci-dessus
est une référence, l'étape visée doit être antérieure et réussie, le champ doit exister.
Elle est partagée par le moteur (qui résout pour appeler) et la gateway (qui résout de son côté
pour comparer l'appel à l'étape du plan approuvé).
"""

from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

REF_KEY: Final = "$from"
MAX_DEPTH: Final = 8


class UnresolvedReference(Exception):
    """Référence invalide ou sans valeur. Le message ne contient aucune valeur."""


def is_reference(value: object) -> bool:
    return isinstance(value, dict) and REF_KEY in value


def parse_reference(value: Mapping[str, JsonValue]) -> tuple[int, str]:
    """Forme exacte `{"$from": {"step": int, "field": str}}`, sinon `UnresolvedReference`."""
    body = value.get(REF_KEY)
    if len(value) != 1 or not isinstance(body, dict) or set(body) != {"step", "field"}:
        raise UnresolvedReference("référence mal formée")
    step, field = body["step"], body["field"]
    if isinstance(step, bool) or not isinstance(step, int) or step < 1:
        raise UnresolvedReference("référence mal formée")
    if not isinstance(field, str) or not field:
        raise UnresolvedReference("référence mal formée")
    return step, field


def resolve(
    value: JsonValue,
    outputs: Mapping[int, Mapping[str, JsonValue]],
    before_seq: int,
    _depth: int = 0,
) -> JsonValue:
    """Remplace les références par la valeur de sortie de l'étape visée.

    `outputs` : sorties des étapes RÉUSSIES, par numéro. `before_seq` : numéro de l'étape qui
    résout ; une référence vers elle-même ou vers l'avant est refusée.
    """
    if _depth > MAX_DEPTH:
        raise UnresolvedReference("paramètre trop profond")
    if isinstance(value, dict):
        if REF_KEY in value:
            step, field = parse_reference(value)
            output = outputs.get(step)
            if step >= before_seq or output is None or field not in output:
                raise UnresolvedReference("référence sans valeur")
            return output[field]
        return {k: resolve(v, outputs, before_seq, _depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, outputs, before_seq, _depth + 1) for v in value]
    return value


def resolve_params(
    params: Mapping[str, JsonValue],
    outputs: Mapping[int, Mapping[str, JsonValue]],
    before_seq: int,
) -> dict[str, JsonValue]:
    resolved = resolve(dict(params), outputs, before_seq)
    assert isinstance(resolved, dict)  # noqa: S101 - `resolve` d'un dict rend un dict
    return resolved
