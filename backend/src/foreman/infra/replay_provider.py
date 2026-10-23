"""Modèle rejoué : répond depuis un enregistrement, sans état, sans réseau.

Le choix de la réponse se fait sur le sha256 du dernier message (égalité exacte), jamais sur une
regex ni des mots-clés. L'entrée `default` rejoue le scénario S1 : démonstration assumée en staging.
`from_dir` fusionne les enregistrements des scénarios : un hash en double ou deux entrées `default`
(dans un fichier ou entre fichiers) sont refusés au démarrage.
"""

import copy
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from foreman.core.catalog import CatalogError, parse_yaml_mapping
from foreman.core.ports import ConversationMessage, ModelReply, ToolCall
from foreman.infra.file_catalog import read_catalog_file

RECORDINGS_DIR: Final = "recordings"
S01_RECORDING: Final = "s01.yaml"
# Enregistrements chargés par `from_dir`, dans l'ordre. Le premier est obligatoire ; les suivants
# sont facultatifs tant que leur scénario n'est pas livré (S2 : semaine 3, PR suivante).
SCENARIO_RECORDINGS: Final = (S01_RECORDING, "s02.yaml", "s10.yaml", "s13.yaml")


class RecordingNotFound(Exception):
    """Aucune entrée de l'enregistrement ne correspond au dernier message."""


class RecordingInvalid(Exception):
    """L'enregistrement est illisible ou invalide (détecté au démarrage)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _When(_Strict):
    last_user_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None = None
    default: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        if (self.last_user_sha256 is None) == (self.default is not True):
            raise ValueError("exactement un de last_user_sha256 et default: true")
        return self


class _RecordedCall(_Strict):
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class _Reply(_Strict):
    text: str
    tool_calls: list[_RecordedCall] = Field(default_factory=list)


class _Exchange(_Strict):
    when: _When
    reply: _Reply


class _Recording(_Strict):
    version: Annotated[int, Field(strict=True)]
    exchanges: Annotated[list[_Exchange], Field(min_length=1)]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.version != 1:
            raise ValueError("version d'enregistrement inconnue")
        keys = [e.when.last_user_sha256 for e in self.exchanges if not e.when.default]
        if len(keys) != len(set(keys)):
            raise ValueError("hash en double")
        if sum(1 for e in self.exchanges if e.when.default) > 1:
            raise ValueError("une seule entrée default")
        return self


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(recording: Path, root: Path) -> _Recording:
    try:
        data = parse_yaml_mapping(read_catalog_file(recording, root), recording.name)
        return _Recording.model_validate(data)
    except (CatalogError, ValidationError):
        # `from None` : les causes citent le contenu du fichier.
        raise RecordingInvalid(f"enregistrement illisible : {recording.name}") from None


class ReplayProvider:
    """Implémente `Provider`. Les enregistrements sont lus et validés à la construction."""

    def __init__(self, *recordings: Path, base: Path | None = None) -> None:
        if not recordings:
            raise RecordingInvalid("aucun enregistrement")
        parsed = [_load(r, base if base is not None else r.parent) for r in recordings]
        self._by_hash: dict[str | None, _Reply] = {}
        self._default: _Reply | None = None
        for exchange in (e for rec in parsed for e in rec.exchanges):
            if exchange.when.default:
                if self._default is not None:
                    raise RecordingInvalid("une seule entrée default")
                self._default = exchange.reply
            elif exchange.when.last_user_sha256 in self._by_hash:
                raise RecordingInvalid("hash en double")
            else:
                self._by_hash[exchange.when.last_user_sha256] = exchange.reply

    @classmethod
    def from_dir(cls, catalog_dir: Path) -> Self:
        """`recordings/s01.yaml` (obligatoire) puis les autres scénarios présents."""
        folder = catalog_dir / RECORDINGS_DIR
        paths = [folder / name for name in SCENARIO_RECORDINGS]
        present = [paths[0], *(p for p in paths[1:] if p.is_file())]
        return cls(*present, base=catalog_dir)

    async def complete(self, messages: Sequence[ConversationMessage]) -> ModelReply:
        last = messages[-1].text if messages else ""
        reply = self._by_hash.get(sha256_of(last), self._default)
        if reply is None:
            raise RecordingNotFound
        return ModelReply(
            text=reply.text,
            tool_calls=tuple(
                ToolCall(c.name, copy.deepcopy(c.arguments)) for c in reply.tool_calls
            ),
        )
