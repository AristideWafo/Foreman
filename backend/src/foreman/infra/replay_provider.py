"""Modèle rejoué : répond depuis un enregistrement, sans état, sans réseau.

Le choix de la réponse se fait sur le sha256 du dernier message (égalité exacte), jamais sur une
regex ni des mots-clés. L'entrée `default` rejoue le scénario S1 : démonstration assumée en staging.
"""

import copy
import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from foreman.core.catalog import CatalogError, parse_yaml_mapping
from foreman.core.ports import ModelReply, ToolCall
from foreman.infra.file_catalog import read_catalog_file

RECORDINGS_DIR: Final = "recordings"
S01_RECORDING: Final = "s01.yaml"


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


class ReplayProvider:
    """Implémente `Provider`. L'enregistrement est lu et validé à la construction (démarrage)."""

    def __init__(self, recording: Path, base: Path | None = None) -> None:
        root = base if base is not None else recording.parent
        try:
            data = parse_yaml_mapping(read_catalog_file(recording, root), recording.name)
            parsed = _Recording.model_validate(data)
        except (CatalogError, ValidationError):
            # `from None` : les causes citent le contenu du fichier.
            raise RecordingInvalid(f"enregistrement illisible : {recording.name}") from None
        self._by_hash = {
            e.when.last_user_sha256: e.reply for e in parsed.exchanges if not e.when.default
        }
        self._default = next((e.reply for e in parsed.exchanges if e.when.default), None)

    @classmethod
    def s01(cls, catalog_dir: Path) -> Self:
        return cls(catalog_dir / RECORDINGS_DIR / S01_RECORDING, base=catalog_dir)

    async def complete(self, messages: Sequence[str]) -> ModelReply:
        last = messages[-1] if messages else ""
        reply = self._by_hash.get(sha256_of(last), self._default)
        if reply is None:
            raise RecordingNotFound
        return ModelReply(
            text=reply.text,
            tool_calls=tuple(
                ToolCall(c.name, copy.deepcopy(c.arguments)) for c in reply.tool_calls
            ),
        )
