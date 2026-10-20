"""Objets de requête et de réponse de l'API (contrat figé v1)."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from foreman.core.accounts import PASSWORD_MAX, PASSWORD_MIN
from foreman.core.events import (
    Budget,
    ExecutionResult,
    ExecutionState,
    Invalidation,
    PlanStatus,
    ResourceRef,
    Sha256,
    StepStatus,
)
from foreman.core.identity import Role


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(max_length=120)] = ""
    team_id: UUID | None = None


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: Annotated[str, Field(min_length=1, max_length=4000)]


class MessageAccepted(BaseModel):
    turn_id: UUID


ErrorCode = Literal[
    "not_found",
    "invalid_request",
    "method_not_allowed",
    "turn_in_progress",
    "capacity_exceeded",
    "internal_error",
    "not_implemented",
    "plan_hash_mismatch",
    "plan_not_approvable",
    "execution_in_progress",
    "question_closed",
    "unauthenticated",
    "forbidden",
    "policy_denied",
    "too_many_requests",
    "last_admin",
    "last_team_admin",
    "invalid_invitation",
    "conflict",
]


class ErrorResponse(BaseModel):
    """Erreur opaque : un code, jamais le détail d'une exception ni la saisie de l'utilisateur."""

    error: ErrorCode


class QuestionAnswerRequest(BaseModel):
    """Réponse à une question de clarification, ou report (`defer`)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["answer", "defer"]
    value: Annotated[str | None, Field(min_length=1, max_length=500)] = None

    @model_validator(mode="after")
    def _answer_needs_a_value(self) -> "QuestionAnswerRequest":
        if self.decision == "answer" and self.value is None:
            raise ValueError("value requis pour answer")
        return self


class QuestionAccepted(BaseModel):
    question_id: Annotated[str, Field(max_length=64)]
    status: Literal["answered", "deferred"]


class ApprovalRequest(BaseModel):
    """Approbation d'un plan : elle porte sur le HASH affiché, pas sur « le dernier plan »."""

    model_config = ConfigDict(extra="forbid")

    plan_hash: Sha256
    decision: Literal["approved"]


class ApprovalAccepted(BaseModel):
    approval_id: UUID
    execution_id: UUID


class ApprovalPending(BaseModel):
    """202 : validé par le développeur, il manque encore l'approbation d'un administrateur."""

    approval_id: UUID
    status: Literal["approval_required"]
    missing: Annotated[list[Literal["admin_approved"]], Field(max_length=1)]


class ApprovalRejected(BaseModel):
    """200 : l'administrateur a refusé le plan (il est invalidé, aucune exécution n'existe)."""

    approval_id: UUID
    status: Literal["rejected"]


class AdminApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_hash: Sha256
    decision: Literal["approved", "rejected"]


class MeTeam(BaseModel):
    id: UUID
    name: Annotated[str, Field(max_length=100)]
    role: Role


class Me(BaseModel):
    user_id: Annotated[str, Field(max_length=100)]
    name: Annotated[str, Field(max_length=100)]
    role: Role
    # Seulement en mode `session` : à renvoyer dans `X-Foreman-CSRF` sur toute méthode non sûre.
    csrf_token: Annotated[str | None, Field(max_length=100)] = None
    # Seulement en mode `session` : équipes partagées de l'appelant.
    teams: Annotated[list[MeTeam], Field(max_length=500)] | None = None


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=3, max_length=254)]
    password: Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX)]


class AcceptInviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: Annotated[str, Field(min_length=1, max_length=100)]
    email: Annotated[str, Field(min_length=3, max_length=254)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=PASSWORD_MIN, max_length=PASSWORD_MAX)]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    profile: Literal["web", "cli", "worker", "eval"]
    version: Annotated[str, Field(max_length=32, pattern=r"^[A-Za-z0-9._+-]+$")]
    persistence: Literal["memory", "postgres"]


class PlanView(BaseModel):
    id: UUID
    version: Annotated[int, Field(ge=1)]
    status: PlanStatus
    content_hash: Sha256
    content: Annotated[dict[str, JsonValue], Field(description="Contenu canonique haché du plan")]
    created_at: AwareDatetime
    expires_at: AwareDatetime
    invalidation: Invalidation | None = None


class ExecutionStepView(BaseModel):
    step: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(max_length=200)]
    tool: Annotated[str, Field(max_length=100)]
    status: StepStatus
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None


class ExecutionView(BaseModel):
    id: UUID
    plan_id: UUID
    plan_card_id: Annotated[str | None, Field(max_length=100)] = None
    state: ExecutionState
    autonomy_level: Annotated[int, Field(ge=1, le=4)]
    budget: Budget
    steps: Annotated[list[ExecutionStepView], Field(max_length=20)]
    resources: Annotated[list[ResourceRef], Field(max_length=50)]
    result: ExecutionResult | None = None


MemberRole = Literal["developer", "team_admin"]
InvitedRole = Literal["developer", "team_admin", "org_admin"]
Name = Annotated[str, Field(min_length=1, max_length=100)]


class TeamView(BaseModel):
    id: UUID
    name: Name


class CreateTeamRequest(BaseModel):
    """Une équipe naît avec son premier team_admin (compte actif existant)."""

    model_config = ConfigDict(extra="forbid")

    name: Name
    first_admin_id: UUID


class MembershipView(BaseModel):
    team_id: UUID
    team_name: Name
    role: Role


class UserView(BaseModel):
    id: UUID
    email: Annotated[str, Field(max_length=254)]
    name: Name
    disabled: bool
    memberships: Annotated[list[MembershipView], Field(max_length=500)]


class SetRoleRequest(BaseModel):
    """Ajoute le membre à l'équipe ou change son rôle. Jamais `org_admin` ici."""

    model_config = ConfigDict(extra="forbid")

    role: MemberRole


class MoveProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team_id: UUID


class CreateInvitationRequest(BaseModel):
    """`team_id` absent : invitation sans équipe (org_admin seulement). `org_admin` exige l'absence
    d'équipe."""

    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, Field(min_length=3, max_length=254)]
    role: InvitedRole
    team_id: UUID | None = None


class InvitationView(BaseModel):
    id: UUID
    email: Annotated[str, Field(max_length=254)]
    team_id: UUID | None
    role: Role
    expires_at: AwareDatetime


class InvitationCreated(InvitationView):
    """Le lien contient le jeton : montré une seule fois, seul son condensat est stocké."""

    link: Annotated[str, Field(max_length=500)]
