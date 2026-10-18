"""Ports de persistance du moteur : plans, exécutions, registre, audit.

Le cœur définit les interfaces ; `infra` les implémente (mémoire et PostgreSQL), avec la même suite
de tests de contrat. Toute lecture est cloisonnée par projet : une ressource d'un autre projet est
absente (`None`), jamais « interdite ».
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

# Identités de développement (profil web, avant les rôles de la semaine 10) : fixes, upsert sûr.
DEV_USER_ID: Final = UUID("00000000-0000-4000-8000-00000000d001")
DEV_TEAM_ID: Final = UUID("00000000-0000-4000-8000-00000000d002")
DEV_USER_EMAIL: Final = "dev@foreman.local"
DEV_TEAM_NAME: Final = "dev"

LEASE_TTL_S: Final = 60
MAX_AUDIT_DURATION_MS: Final = 2**31 - 1

PlanStatus = Literal[
    "proposed", "dev_approved", "admin_approved", "invalidated", "expired", "executed"
]
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
StepStatus = Literal["pending", "running", "succeeded", "failed", "compensated", "skipped"]


class StoreError(Exception):
    """Échec de stockage. Aucun détail interne (SQL, URL) dans le message."""


class StaleLease(StoreError):
    """Le bail a été repris par un autre worker : l'écriture est refusée."""


class InvalidTransition(StoreError):
    """Transition refusée depuis l'état courant."""


class DuplicateResource(StoreError):
    """La ressource externe est déjà au registre."""


class UnknownProject(StoreError):
    """Le projet n'existe pas."""


# --- Plans ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewPlan:
    project_id: UUID
    content: Mapping[str, object]  # contenu canonique ; `content["steps"]` alimente les étapes
    content_hash: str
    skills_used: Sequence[Mapping[str, object]]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class PlanRecord:
    id: UUID
    project_id: UUID
    version: int
    content: Mapping[str, object]
    content_hash: str
    skills_used: Sequence[Mapping[str, object]]
    status: PlanStatus
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class StepSpec:
    seq: int
    tool: str
    params: Mapping[str, object]
    idempotency_key: str


def steps_of(content: Mapping[str, object]) -> list[StepSpec]:
    """Étapes d'un contenu de plan (clés `seq`, `tool`, `params`, `idempotency_key`)."""
    raw = content.get("steps", [])
    if not isinstance(raw, list):
        raise StoreError("plan invalide")
    try:
        return [
            StepSpec(
                seq=int(step["seq"]),
                tool=str(step["tool"]),
                params=dict(step.get("params", {})),
                idempotency_key=str(step["idempotency_key"]),
            )
            for step in raw
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise StoreError("plan invalide") from exc


@dataclass(frozen=True, slots=True)
class Approved:
    approval_id: UUID
    execution_id: UUID
    created: bool  # faux : plan déjà approuvé, mêmes identifiants rendus


@dataclass(frozen=True, slots=True)
class ApprovalRefused:
    reason: Literal[
        "not_found", "plan_hash_mismatch", "plan_not_approvable", "execution_in_progress"
    ]


ApprovalResult = Approved | ApprovalRefused


class PlanStore(Protocol):
    async def create(self, plan: NewPlan) -> PlanRecord:
        """Version suivante du projet. Lève `UnknownProject`."""
        ...

    async def get(self, project_id: UUID, plan_id: UUID) -> PlanRecord | None: ...

    async def approve(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        autonomy_level: int,
    ) -> ApprovalResult:
        """Atomique : plan `dev_approved` + approbation + exécution + étapes `pending`."""
        ...


# --- Exécutions -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lease:
    execution_id: UUID
    owner: str
    epoch: int


@dataclass(frozen=True, slots=True)
class StepRecord:
    id: UUID
    seq: int
    tool: str
    params: Mapping[str, object]
    idempotency_key: str
    status: StepStatus
    result: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    id: UUID
    plan_id: UUID
    project_id: UUID
    state: ExecutionState
    autonomy_level: int
    steps: Sequence[StepRecord]


@dataclass(frozen=True, slots=True)
class NewReservation:
    """L'étape peut s'exécuter : personne ne l'a réservée avant."""


@dataclass(frozen=True, slots=True)
class CompletedReservation:
    """La clé a déjà abouti : le résultat précédent est rendu, rien ne se rejoue."""

    result: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class OrphanReservation:
    """Réservée sans résultat (panne en cours d'étape) : jamais rejouée à l'aveugle."""


Reservation = NewReservation | CompletedReservation | OrphanReservation


@dataclass(frozen=True, slots=True)
class NewResource:
    provider: str
    resource_type: str
    external_id: str
    external_url: str | None = None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    actor_kind: str
    project_id: UUID | None = None
    plan_id: UUID | None = None
    execution_id: UUID | None = None
    step_seq: int | None = None
    plan_hash: str | None = None
    actor: str | None = None
    tool: str | None = None
    tool_class: str | None = None
    decision: str | None = None
    rule_id: str | None = None
    params_redacted: Mapping[str, object] | None = None
    result_redacted: Mapping[str, object] | None = None
    duration_ms: int | None = None


class ExecutionStore(Protocol):
    async def get(self, project_id: UUID, execution_id: UUID) -> ExecutionRecord | None: ...

    async def claim_lease(
        self, execution_id: UUID, owner: str, ttl_s: int = LEASE_TTL_S
    ) -> Lease | None:
        """Vide si une autre instance tient un bail valide. Chaque prise incrémente le jeton."""
        ...

    async def renew(self, lease: Lease, ttl_s: int = LEASE_TTL_S) -> bool: ...

    async def next_step(self, execution_id: UUID) -> StepRecord | None:
        """Première étape non réussie (point de reprise)."""
        ...

    async def reserve_idempotency(self, lease: Lease, step_seq: int) -> Reservation:
        """Réserve la clé (`INSERT … ON CONFLICT DO NOTHING`) et passe l'étape à `running`."""
        ...

    async def complete_step(
        self,
        lease: Lease,
        step_seq: int,
        result: Mapping[str, object],
        created_resources: Sequence[NewResource],
        audit: Sequence[AuditEntry],
    ) -> None:
        """UNE transaction : étape réussie, clé terminée, ressources au registre, audit.

        Lève `StaleLease`, `InvalidTransition`, `DuplicateResource` ou `StoreError` : rien d'écrit.
        """
        ...

    async def finish(self, lease: Lease, state: Literal["succeeded", "blocked"]) -> None: ...


# --- Registre et audit ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    id: UUID
    project_id: UUID
    execution_id: UUID | None
    provider: str
    resource_type: str
    external_id: str
    external_url: str | None
    origin: str


class ResourceRegistry(Protocol):
    async def contains(self, provider: str, resource_type: str, external_id: str) -> bool: ...

    async def list_for_project(self, project_id: UUID) -> list[ResourceRecord]: ...


class AuditLog(Protocol):
    async def append(self, entry: AuditEntry) -> None:
        """Lève `StoreError` si l'entrée est invalide (rien n'est écrit)."""
        ...

    async def list_for_project(self, project_id: UUID, limit: int = 200) -> list[AuditEntry]: ...


@dataclass(frozen=True, slots=True)
class Stores:
    plans: PlanStore
    executions: ExecutionStore
    registry: ResourceRegistry
    audit: AuditLog
