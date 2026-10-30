"""Clarification : les questions ouvertes que l'agent pose au développeur (`ask_user`).

`ask_user` est un outil de classe `control` : il n'écrit rien à l'extérieur et ne passe donc pas par
la gateway. Le modèle ne fournit que le champ visé et la formulation ; le serveur décide du reste :
identifiants des questions, options (lues dans les référentiels, jamais proposées par le modèle),
nombre de questions et budget de tours. Le schéma des champs vient de `project-schema.yaml`.

Format des identifiants : `q<tour>-<rang>` (le tour sert à compter le budget sans état de plus).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from foreman.core.catalog import Catalog, CatalogError
from foreman.core.events import ClarificationCardData, ClarificationQuestion, QuestionStatus

ASK_USER: Final = "ask_user"
SCHEMA_REFERENTIEL: Final = "project-schema"
MAX_QUESTIONS: Final = 5
MAX_PROMPT_CHARS: Final = 300
MAX_ROUNDS: Final = 3
MAX_OPTIONS: Final = 10
MAX_OPTION_CHARS: Final = 100
_ID: Final = re.compile(r"^q(\d{1,3})-(\d{1,2})$")


class ClarificationRefused(Exception):
    """`ask_user` refusé (arguments invalides ou budget épuisé). Message fixe, aucun détail."""

    def __init__(self) -> None:
        super().__init__("clarification refusée")


class AskUserQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: Annotated[str, Field(min_length=1, max_length=50)]
    prompt: Annotated[str, Field(min_length=1, max_length=MAX_PROMPT_CHARS)]
    # Pistes de réponse ; gardées seulement pour un champ libre (hors schéma ou sans options).
    suggestions: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=MAX_OPTION_CHARS)]],
        Field(max_length=MAX_OPTIONS),
    ] = []

    @field_validator("field", "prompt", "suggestions")
    @classmethod
    def _no_nul(cls, value: str | list[str]) -> str | list[str]:
        items = [value] if isinstance(value, str) else value
        if any("\x00" in item for item in items):  # PostgreSQL refuse \u0000 dans un JSONB
            raise ValueError("caractère nul")
        return value


class AskUserArguments(BaseModel):
    """Arguments validés de `ask_user`. Les options n'en font pas partie (`extra=forbid`)."""

    model_config = ConfigDict(extra="forbid")

    questions: Annotated[list[AskUserQuestion], Field(min_length=1, max_length=MAX_QUESTIONS)]


class _OptionsFrom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    referentiel: str
    key: str


class _FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required: bool = False
    description: Annotated[str, Field(max_length=300)] = ""
    options_from: _OptionsFrom | None = None


class _SchemaFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Annotated[int, Field(strict=True)]
    fields: Annotated[dict[str, _FieldSpec], Field(min_length=1)]


@dataclass(frozen=True, slots=True)
class FieldRule:
    required: bool
    options: tuple[str, ...]  # vide : réponse libre


def round_of(question_id: str) -> int:
    """Tour d'une question (0 si l'identifiant n'a pas la forme serveur)."""
    match = _ID.match(question_id)
    return int(match.group(1)) if match else 0


def card_id_for(round_: int) -> str:
    return f"clarification-{round_}"


def card_of(round_: int, questions: Sequence[ClarificationQuestion]) -> ClarificationCardData:
    """Carte d'un tour : toutes les questions de ce tour, réémise entière à chaque changement."""
    return ClarificationCardData(
        card_id=card_id_for(round_),
        kind="clarification",
        questions=[q for q in questions if round_of(q.id) == round_],
    )


def answer_text(field: str, value: str) -> str:
    """Texte canonique du message utilisateur d'une réponse (produit par la route, jamais tapé).

    Le replay des scénarios hache ce texte exact : ne pas le modifier sans régénérer les
    enregistrements.
    """
    return f"Réponse à la clarification : {field} = {value}"


def with_status(
    questions: Sequence[ClarificationQuestion],
    question_id: str,
    status: QuestionStatus,
    answer: str | None = None,
) -> list[ClarificationQuestion]:
    return [
        q.model_copy(update={"status": status, "answer": answer}) if q.id == question_id else q
        for q in questions
    ]


class ClarificationRules:
    """Règles issues du schéma de projet (champs, obligations, options imposées par le serveur)."""

    def __init__(self, fields: Mapping[str, FieldRule]) -> None:
        self._fields = dict(fields)

    @classmethod
    def from_catalog(cls, catalog: Catalog) -> "ClarificationRules":
        """Lit `project-schema` ; une erreur arrête le démarrage (`CatalogError`)."""
        reference = catalog.referentiels.get(SCHEMA_REFERENTIEL)
        if reference is None:
            raise CatalogError(f"référentiel manquant : {SCHEMA_REFERENTIEL}")
        try:
            parsed = _SchemaFile.model_validate(reference.data)
        except ValidationError:
            raise CatalogError(f"référentiel invalide : {SCHEMA_REFERENTIEL}") from None
        if parsed.version != 1:
            raise CatalogError(f"référentiel invalide : {SCHEMA_REFERENTIEL}")
        fields: dict[str, FieldRule] = {}
        for name, spec in parsed.fields.items():
            options: tuple[str, ...] = ()
            if spec.options_from is not None:
                other = catalog.referentiels.get(spec.options_from.referentiel)
                table = other.data.get(spec.options_from.key) if other else None
                if not isinstance(table, dict):
                    raise CatalogError(f"options introuvables pour le champ {name}")
                options = tuple(table)
                if len(options) > MAX_OPTIONS or any(
                    not 1 <= len(o) <= MAX_OPTION_CHARS for o in options
                ):
                    raise CatalogError(f"options invalides pour le champ {name}")
            fields[name] = FieldRule(spec.required, options)
        return cls(fields)

    def blocking(self, questions: Sequence[ClarificationQuestion]) -> bool:
        """Vrai si une question OUVERTE porte sur un champ requis : on ne planifie pas encore."""
        return any(
            q.status == "open" and (rule := self._fields.get(q.field)) and rule.required
            for q in questions
        )

    def ask(
        self, arguments: AskUserArguments, existing: Sequence[ClarificationQuestion]
    ) -> tuple[int, list[ClarificationQuestion]]:
        """Nouvelles questions (tour, questions) ou `ClarificationRefused`. Pure, rien n'est écrit.

        Refus : budget de tours épuisé, champ hors schéma, champ répété, champ déjà en question
        ouverte. Les options viennent du schéma, jamais du modèle.
        """
        round_ = 1 + max((round_of(q.id) for q in existing), default=0)
        open_rounds = {round_of(q.id) for q in existing if q.status == "open"}
        # shortcut: budget = tours encore ouverts, pas à vie ; id sur 3 chiffres (999).
        if round_ > 999 or len(open_rounds) >= MAX_ROUNDS:
            raise ClarificationRefused
        names = [q.field for q in arguments.questions]
        already_open = {q.field for q in existing if q.status == "open"}
        if (
            len(set(names)) != len(names)
            or any(n not in self._fields for n in names)
            or already_open.intersection(names)
        ):
            raise ClarificationRefused
        return round_, [
            ClarificationQuestion(
                id=f"q{round_}-{index}",
                field=q.field,
                prompt=q.prompt,
                options=list(self._fields[q.field].options),
                suggestions=[]
                if self._fields[q.field].options
                else list(dict.fromkeys(q.suggestions)),
                status="open",
            )
            for index, q in enumerate(arguments.questions, start=1)
        ]


def accepts(question: ClarificationQuestion, value: str) -> bool:
    """La réponse est-elle recevable ? Avec options : une d'entre elles, exactement."""
    if "\x00" in value:
        return False
    if question.options:
        return value in question.options
    return bool(value.strip())
