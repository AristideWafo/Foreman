"""Aliasing stable (ADR 0002, couche 4) : le modèle corrèle sans voir la valeur.

Hôtes (`host-1`) et valeurs d'affectations `NOM=valeur` (`var-A`) deviennent des alias numérotés
dans l'ordre de première apparition. L'objet vit le temps d'un calcul d'historique : celui-ci est
reconstruit du journal (qui ne fait que s'allonger), donc la même valeur reçoit le même alias d'un
message à l'autre, d'un tour à l'autre. À la réponse, `restore` remet les valeurs d'origine.

shortcut: hôtes d'URL, IPv4 et noms en `.internal|.local|.lan|.corp|.com|.org|.net|.io|.fr|.dev|
.cloud` ; une valeur interne d'une autre forme n'est pas aliasée (elle reste visible du modèle).
"""

import re
from collections.abc import Mapping
from typing import Final

_HOST: Final = re.compile(
    r"(?<=://)[^\s/?#\"']{1,255}"
    r"|\b\d{1,3}(?:\.\d{1,3}){3}\b"
    r"|\b(?:[a-z0-9\-]{1,63}\.){1,5}(?:internal|local|lan|corp|com|org|net|io|fr|dev|cloud)\b",
    re.IGNORECASE,
)
# `NOM_EN_MAJUSCULES=valeur` : les secrets sont déjà masqués (`[masqué]`) avant l'aliasing.
_VAR: Final = re.compile(r"\b([A-Z][A-Z0-9_]{2,})=(?!host-)([^\s\"',;\[]{3,})")
_ALIAS: Final = re.compile(r"\b(host-\d{1,4}|var-[A-Z]{1,3})\b")
MAX_ALIASES: Final = 500  # au-delà, les nouvelles valeurs ne sont plus aliasées mais masquées
OVERFLOW: Final = "[valeur]"


def _letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


class Aliases:
    def __init__(self) -> None:
        self._alias_of: dict[tuple[str, str], str] = {}
        self._original: dict[str, str] = {}
        self._hosts = 0
        self._vars = 0

    def _alias(self, kind: str, value: str) -> str:
        key = (kind, value.lower() if kind == "host" else value)
        if (known := self._alias_of.get(key)) is not None:
            return known
        if len(self._alias_of) >= MAX_ALIASES:
            return OVERFLOW
        if kind == "host":
            self._hosts += 1
            alias = f"host-{self._hosts}"
        else:
            alias = f"var-{_letters(self._vars)}"
            self._vars += 1
        self._alias_of[key] = alias
        self._original[alias] = value
        return alias

    def apply(self, text: str) -> str:
        """Texte sans hôte ni valeur d'affectation : seuls les alias restent."""
        text = _HOST.sub(lambda m: self._alias("host", m.group(0)), text)
        return _VAR.sub(lambda m: f"{m.group(1)}={self._alias('var', m.group(2))}", text)

    def restore(self, value: object) -> object:
        """Remet les valeurs d'origine dans une réponse du modèle (texte, listes, objets)."""
        if isinstance(value, str):
            return _ALIAS.sub(lambda m: self._original.get(m.group(0), m.group(0)), value)
        if isinstance(value, Mapping):
            return {str(k): self.restore(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [self.restore(v) for v in value]
        return value
