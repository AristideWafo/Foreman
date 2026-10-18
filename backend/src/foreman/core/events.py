"""Événements du flux d'un projet : contrat figé v1 (voir docs/plans/semaine-1.md et semaine-2.md).

Règle d'évolution : un ajout (nouveau `type`, nouveau champ optionnel) garde `v: 1` ;
tout autre changement passe à `v: 2`. Le front ignore les types qu'il ne connaît pas.

Les clients IGNORENT les champs inconnus et ne valident pas `additionalProperties` (le schéma publié
le déclare faux pour les modèles émis par le serveur : c'est de la rigueur côté émission, pas une
consigne de validation côté client) ; sans cela, aucun ajout ne serait réellement additif.

Sémantique de `seq` : strictement croissant, contigu à partir de 1, par projet, livré dans l'ordre.
Une carte (`card`) remplace la précédente de même `card_id`. Trois sortes de cartes (`kind`) :
`plan`, `execution` et `clarification` (ajout additif de la Semaine 3).

Ordre et portée (Semaine 2) :
- après l'approbation, la carte plan est RÉÉMISE (`status: dev_approved`, `approvable: false`)
  AVANT la carte d'exécution ;
- la carte d'exécution est émise AVANT tout `execution_step` ou `execution_log` de même `card_id` ;
- `execution_step.card_id` et `execution_log.card_id` désignent la carte d'EXÉCUTION
  (jamais la carte plan) ;
  un `execution_step` ou un `execution_log` dont la carte est inconnue est ignoré ;
- les lignes de journal (`execution_log`) sont déjà filtrées par la Tool Gateway.
"""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

StepStatus = Literal["pending", "running", "succeeded", "failed", "compensated", "skipped"]
ToolClass = Literal["read", "write_registry", "write_foreign", "destructive", "control"]
Reversibility = Literal["reversible", "compensable", "irreversible", "not_applicable"]
# Tous les états de la spec dès maintenant : en ajouter plus tard casserait un client strict.
ExecutionState = Literal[
    "running",
    "awaiting_permission",
    "awaiting_remediation",
    "succeeded",
    "partial",
    "failed_compensated",
    "blocked",
    "degraded",
]
# Les six états de la spec, en un seul vocabulaire (carte plan ET `PlanView`) : en ajouter un
# plus tard casserait un client strict.
PlanStatus = Literal[
    "proposed", "dev_approved", "admin_approved", "invalidated", "expired", "executed"
]
# Clé d'un dictionnaire libre : sans `_` ni majuscule (`__proto__` piégerait un `Object.assign`).
SlugKey = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,49}$")]
# Seuls http et https, avec un hôte, sans espace ni contrôle : jamais de lien `javascript:`.
Url = Annotated[str, Field(max_length=500, pattern=r"^https?://[^\s\x00-\x1f\x7f]+$")]
Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _EventBase(_Model):
    v: Literal[1] = 1
    seq: Annotated[
        int,
        Field(ge=1, description="Strictement croissant, contigu à partir de 1, par projet"),
    ]
    project_id: UUID
    turn_id: UUID
    at: Annotated[AwareDatetime, Field(description="Horodatage avec fuseau (UTC)")]


class MessageData(_Model):
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(max_length=8000)]


class CardStep(_Model):
    step: Annotated[int, Field(ge=1, description="Indice de l'étape dans la carte")]
    title: Annotated[str, Field(max_length=200)]
    status: StepStatus
    tool: Annotated[str | None, Field(max_length=100)] = None
    tool_class: ToolClass | None = None
    reversibility: Reversibility | None = None


class SkillRef(_Model):
    name: Annotated[str, Field(max_length=100)]
    version: Annotated[int, Field(ge=1)]
    sha256: Sha256


class ExpectedResource(_Model):
    provider: Annotated[str, Field(max_length=50)]
    resource_type: Annotated[str, Field(max_length=50)]
    name: Annotated[str, Field(max_length=200)]


class PlanCardData(_Model):
    card_id: Annotated[str, Field(max_length=64)]
    # Sans valeur par défaut : le discriminant doit être requis dans le schéma publié.
    kind: Literal["plan"]
    title: Annotated[str, Field(max_length=200)]
    summary: Annotated[str, Field(max_length=500)]
    steps: Annotated[list[CardStep], Field(max_length=20)]
    # Champs ajoutés par la Semaine 2 (tous facultatifs : additif en v1).
    plan_id: UUID | None = None
    plan_hash: Sha256 | None = None
    status: PlanStatus | None = None
    environment: Annotated[str | None, Field(max_length=50)] = None
    autonomy_level: Annotated[int | None, Field(ge=1, le=4)] = None
    stack: Annotated[
        dict[SlugKey, Annotated[str, Field(max_length=100)]] | None, Field(max_length=10)
    ] = None
    skills: Annotated[list[SkillRef] | None, Field(max_length=10)] = None
    expected_resources: Annotated[list[ExpectedResource] | None, Field(max_length=50)] = None
    approvable: Annotated[
        bool | None, Field(description="Décidé par le serveur d'après la matrice de droits")
    ] = None


class Budget(_Model):
    tool_calls_used: Annotated[int, Field(ge=0)]
    tool_calls_max: Annotated[int, Field(ge=0)]
    elapsed_s: Annotated[int, Field(ge=0)]
    max_minutes: Annotated[int, Field(ge=0)]


class ResourceRef(_Model):
    provider: Annotated[str, Field(max_length=50)]
    resource_type: Annotated[str, Field(max_length=50)]
    name: Annotated[str, Field(max_length=200)]
    url: Url | None = None


class Link(_Model):
    label: Annotated[str, Field(max_length=100)]
    url: Url


class ExecutionResult(_Model):
    summary: Annotated[str, Field(max_length=500)]
    links: Annotated[list[Link], Field(max_length=10)] = []


class ExecutionCardData(_Model):
    """Carte d'exécution : réémise entière (remplacement par `card_id`) à chaque changement."""

    card_id: Annotated[str, Field(max_length=64)]
    kind: Literal["execution"]
    execution_id: UUID
    plan_card_id: Annotated[str, Field(max_length=64)]
    state: ExecutionState
    autonomy_level: Annotated[int, Field(ge=1, le=4)]
    steps: Annotated[list[CardStep], Field(max_length=20)]
    budget: Budget
    resources: Annotated[list[ResourceRef], Field(max_length=50)] = []
    result: ExecutionResult | None = None


QuestionStatus = Literal["open", "answered", "deferred"]


class ClarificationQuestion(_Model):
    id: Annotated[str, Field(min_length=1, max_length=64)]
    field: Annotated[str, Field(min_length=1, max_length=50, description="Champ du plan visé")]
    prompt: Annotated[str, Field(min_length=1, max_length=300)]
    options: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]],
        Field(max_length=10, description="Choix proposés ; vide = réponse libre"),
    ] = []
    status: QuestionStatus
    answer: Annotated[str | None, Field(max_length=500)] = None


class ClarificationCardData(_Model):
    """Carte de clarification : réémise entière (remplacement par `card_id`) à chaque réponse."""

    card_id: Annotated[str, Field(max_length=64)]
    kind: Literal["clarification"]
    questions: Annotated[list[ClarificationQuestion], Field(max_length=5)]


CardData = Annotated[
    PlanCardData | ExecutionCardData | ClarificationCardData, Field(discriminator="kind")
]


class ExecutionStepData(_Model):
    card_id: Annotated[str, Field(max_length=64)]
    step: Annotated[int, Field(ge=1, description="Indice de l'étape dans la carte")]
    status: StepStatus


class ExecutionLogData(_Model):
    """Lignes de journal d'une étape, déjà filtrées par la gateway (secrets masqués)."""

    card_id: Annotated[str, Field(max_length=64)]
    step: Annotated[int, Field(ge=1)]
    lines: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=50)]


class TurnStatusData(_Model):
    status: Literal["running", "completed", "failed"]


ERROR_MESSAGES = {
    "internal_error": "Une erreur est survenue. Réessayez.",
    "unknown_tool": "L'agent a demandé une action qui n'existe pas.",
    "invalid_plan": "Le plan proposé par l'agent est invalide.",
}


class ErrorData(_Model):
    code: Literal["internal_error", "unknown_tool", "invalid_plan"]
    message: Annotated[str, Field(description="Texte fixe dérivé de `code`, jamais une exception")]

    @model_validator(mode="after")
    def _message_is_the_fixed_text(self) -> "ErrorData":
        if self.message != ERROR_MESSAGES[self.code]:
            raise ValueError("message non conforme au code")
        return self


class MessageEvent(_EventBase):
    type: Literal["message"] = "message"
    data: MessageData


class CardEvent(_EventBase):
    type: Literal["card"] = "card"
    data: CardData


class ExecutionStepEvent(_EventBase):
    type: Literal["execution_step"] = "execution_step"
    data: ExecutionStepData


class ExecutionLogEvent(_EventBase):
    type: Literal["execution_log"] = "execution_log"
    data: ExecutionLogData


class TurnStatusEvent(_EventBase):
    type: Literal["turn_status"] = "turn_status"
    data: TurnStatusData


class ErrorEvent(_EventBase):
    type: Literal["error"] = "error"
    data: ErrorData


Event = Annotated[
    MessageEvent
    | CardEvent
    | ExecutionStepEvent
    | ExecutionLogEvent
    | TurnStatusEvent
    | ErrorEvent,
    Field(discriminator="type"),
]


EventData = (
    MessageData
    | PlanCardData
    | ExecutionCardData
    | ClarificationCardData
    | ExecutionStepData
    | ExecutionLogData
    | TurnStatusData
    | ErrorData
)
AnyEvent = (
    MessageEvent | CardEvent | ExecutionStepEvent | ExecutionLogEvent | TurnStatusEvent | ErrorEvent
)


def make_event(seq: int, project_id: UUID, turn_id: UUID, data: EventData) -> AnyEvent:
    """Enveloppe `data` : le type de l'événement se déduit de la charge utile."""
    at = datetime.now(UTC)
    match data:
        case MessageData():
            return MessageEvent(seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data)
        case PlanCardData() | ExecutionCardData() | ClarificationCardData():
            return CardEvent(seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data)
        case ExecutionLogData():
            return ExecutionLogEvent(
                seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data
            )
        case ExecutionStepData():
            return ExecutionStepEvent(
                seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data
            )
        case TurnStatusData():
            return TurnStatusEvent(
                seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data
            )
        case ErrorData():
            return ErrorEvent(seq=seq, project_id=project_id, turn_id=turn_id, at=at, data=data)
