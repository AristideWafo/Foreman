"""Ports de persistance du moteur : plans, exécutions, registre, audit.

Le cœur définit les interfaces ; `infra` les implémente (mémoire et PostgreSQL), avec la même suite
de tests de contrat. Toute lecture est cloisonnée par projet : une ressource d'un autre projet est
absente (`None`), jamais « interdite ».
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

# Identités de développement (utilisateur `dev` du mode `none`) : fixes, upsert sûr.
DEV_USER_ID: Final = UUID("00000000-0000-4000-8000-00000000d001")
DEV_TEAM_ID: Final = UUID("00000000-0000-4000-8000-00000000d002")
DEV_USER_NAME: Final = "dev"  # nom du membre du mode `none`
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
    requested_by: UUID  # demandeur authentifié par le serveur, jamais lu du corps de requête


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
    requested_by: UUID | None = None  # vide pour les plans antérieurs à la migration 0003
    # `{reason, changes}` si et seulement si le plan est `invalidated` (CHECK de la migration 0005).
    # `expired` n'en porte pas : sa raison n'existe que dans la carte.
    invalidation: Mapping[str, object] | None = None


EXECUTION_ID_PLACEHOLDER: Final = "{execution_id}"  # gabarit haché dans le plan


@dataclass(frozen=True, slots=True)
class StepSpec:
    seq: int
    tool: str
    params: Mapping[str, object]
    idempotency_key: str

    def bound_to(self, execution_id: UUID) -> "StepSpec":
        """Clé d'idempotence définitive : `{execution_id}` est substitué à l'approbation."""
        key = self.idempotency_key.replace(EXECUTION_ID_PLACEHOLDER, str(execution_id))
        return replace(self, idempotency_key=key)


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
class AwaitingAdmin:
    """Validation développeur écrite SANS exécution : il manque l'approbation d'un admin."""

    approval_id: UUID
    created: bool  # faux : déjà validé par le développeur, même identifiant rendu


@dataclass(frozen=True, slots=True)
class Rejected:
    """Refus de l'administrateur : le plan est `invalidated`."""

    approval_id: UUID
    created: bool


@dataclass(frozen=True, slots=True)
class ApprovalRefused:
    reason: Literal[
        "not_found",
        "plan_hash_mismatch",
        "plan_not_approvable",
        "execution_in_progress",
        "forbidden",  # le rôle ne peut pas donner cette approbation : rien n'est écrit
        "policy_denied",  # une étape du plan est interdite au rôle du demandeur
    ]


@dataclass(frozen=True, slots=True)
class Invalidated:
    """Plan passé à `invalidated` (ou déjà : `created` faux, rien n'est réécrit)."""

    created: bool


ADMIN_REJECTED: Final[Mapping[str, object]] = {"reason": "admin_rejected", "changes": []}

ApprovalResult = Approved | AwaitingAdmin | ApprovalRefused
AdminApprovalResult = Approved | ApprovalRefused
AdminRejectionResult = Rejected | ApprovalRefused
InvalidationResult = Invalidated | ApprovalRefused

# Rôles qui peuvent donner l'approbation admin (défense en profondeur : la matrice `approvers`
# est la source, le dépôt refuse en plus un développeur).
ADMIN_ROLES: Final = ("team_admin", "org_admin")


def system_audit(plan: PlanRecord, decision: str, rule_id: str) -> "AuditEntry":
    """Audit d'une transition écrite par le système (invalidation, expiration) : un seul gabarit
    pour les deux dépôts. `AuditEntry` est défini plus bas, d'où l'annotation différée."""
    return AuditEntry(
        actor_kind="system",
        project_id=plan.project_id,
        plan_id=plan.id,
        plan_hash=plan.content_hash,
        decision=decision,
        rule_id=rule_id,
    )


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
        start_execution: bool = True,
        *,
        now: datetime,
    ) -> ApprovalResult:
        """Atomique : plan `dev_approved` + approbation + exécution + étapes `pending`.

        Sans `start_execution`, seuls le plan et l'approbation sont écrits (`AwaitingAdmin`) :
        l'exécution naît de `approve_admin`.

        `now` est l'horloge du service, seule source de temps (échéance comprise). Un plan échu
        sans exécution est écrit `expired`, avec son audit, dans la même transaction, puis refusé.
        """
        ...

    async def approve_admin(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        approver_role: str,
        autonomy_level: int,
        *,
        now: datetime,
    ) -> AdminApprovalResult:
        """Atomique : approbation `admin` + exécution + étapes. Idempotent. Un développeur est
        refusé (`forbidden`, rien d'écrit) ; le plan doit être `dev_approved` et non expiré."""
        ...

    async def reject_admin(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        approver_role: str,
        *,
        now: datetime,
    ) -> AdminRejectionResult:
        """Atomique : approbation `admin` refusée + plan `invalidated` (`ADMIN_REJECTED`) + audit.
        Idempotent."""
        ...

    async def invalidate(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        invalidation: Mapping[str, object],
        now: datetime,
    ) -> InvalidationResult:
        """`proposed` ou `dev_approved` sans exécution -> `invalidated`, avec audit système
        (`decision: invalidated`, `rule_id` = raison) dans la même transaction. Idempotent
        (`created`). Le hash est vérifié ; un plan échu est écrit `expired` et refusé."""
        ...

    async def expire_due(self, now: datetime) -> list[PlanRecord]:
        """Écrit `expired` (+ audit système) pour chaque plan `proposed` ou `dev_approved` échu
        et sans exécution. Rend ceux qui viennent de changer d'état (un 2e appel rend [])."""
        ...

    async def has_admin_approval(self, plan_id: UUID, plan_hash: str) -> bool:
        """Une approbation `admin` approuvée existe pour ce plan ET ce hash."""
        ...


# --- Exécutions -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Lease:
    execution_id: UUID
    owner: str
    epoch: int
    # Portée d'idempotence des adaptateurs non durables (voir `Gateway.idempotency_scope`) : la
    # clé réservée est `clé de l'étape + key_suffix`. Vide pour des adaptateurs durables.
    key_suffix: str = ""

    def key(self, step_key: str) -> str:
        return step_key + self.key_suffix


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
class ExecutionRef:
    project_id: UUID
    execution_id: UUID


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
class TakenOverReservation:
    """Réservation orpheline rattachée à l'étape courante : l'étape peut s'exécuter."""


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


def ensure_audit_scope(entries: Sequence[AuditEntry], project_id: UUID, execution_id: UUID) -> None:
    """Une étape n'écrit que l'audit de SON projet et de SON exécution (sinon `StoreError`)."""
    for entry in entries:
        if entry.project_id != project_id or entry.execution_id not in (None, execution_id):
            raise StoreError("audit invalide")


MAX_RESUMABLE: Final = 100


class ExecutionStore(Protocol):
    async def get(self, project_id: UUID, execution_id: UUID) -> ExecutionRecord | None: ...

    async def list_resumable(self) -> list[ExecutionRef]:
        """Exécutions `running` (au plus `MAX_RESUMABLE`, les plus anciennes d'abord).

        Appelé au démarrage : le bail décide ensuite qui peut les reprendre.
        """
        ...

    async def claim_lease(
        self, execution_id: UUID, owner: str, ttl_s: int = LEASE_TTL_S
    ) -> Lease | None:
        """Vide si une autre instance tient un bail valide. Chaque prise incrémente le jeton."""
        ...

    async def renew(self, lease: Lease, ttl_s: int = LEASE_TTL_S) -> bool:
        """Faux si le bail n'est plus le nôtre ou a expiré (il se reprend par `claim_lease`)."""
        ...

    async def next_step(self, execution_id: UUID) -> StepRecord | None:
        """Première étape non réussie (point de reprise)."""
        ...

    async def reserve_idempotency(self, lease: Lease, step_seq: int) -> Reservation:
        """Réserve la clé (`INSERT … ON CONFLICT DO NOTHING`) et passe l'étape à `running`."""
        ...

    async def take_over(self, lease: Lease, step_seq: int) -> TakenOverReservation:
        """Rattache la clé `reserved` (orpheline) à l'étape courante, en une transaction.

        L'appelant décide si la reprise est sûre (outil `read` ou idempotent).
        `InvalidTransition` si la clé n'est plus orpheline ; `StaleLease` si le bail a changé.
        """
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

        Chaque entrée d'audit doit appartenir à cette exécution (même projet, même exécution si
        elle est renseignée) : sinon `StoreError`. Lève `StaleLease`, `InvalidTransition`,
        `DuplicateResource` ou `StoreError` : rien d'écrit.
        """
        ...

    async def release(
        self, lease: Lease, step_seq: int | None, *, keep_lease: bool = False
    ) -> None:
        """Arrêt propre : libère le bail et, si `step_seq` est donné, l'étape réservée SANS résultat
        (réservation supprimée, étape `pending`). Sans effet sur une étape déjà réussie.

        À ne pas confondre avec un crash : sans appel à `release`, la réservation reste orpheline
        et la reprise bloque l'exécution. `keep_lease` : ne libère que la réservation (refus avant
        effet ; le bail sert encore au blocage). Lève `StaleLease` si le bail n'est plus le nôtre.
        """
        ...

    async def finish(self, lease: Lease, state: Literal["succeeded", "blocked"]) -> None:
        """`succeeded` exige que toutes les étapes le soient (`InvalidTransition` sinon)."""
        ...


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
    async def contains(
        self, project_id: UUID, provider: str, resource_type: str, external_id: str
    ) -> bool:
        """Vrai seulement si la ressource est au registre DE CE PROJET (jamais d'un autre)."""
        ...

    async def exists_elsewhere(
        self, project_id: UUID, provider: str, resource_type: str, external_id: str
    ) -> bool:
        """Vrai si la ressource est au registre d'un AUTRE projet (un seul maître)."""
        ...

    async def list_for_project(self, project_id: UUID) -> list[ResourceRecord]: ...


class AuditLog(Protocol):
    async def append(self, entry: AuditEntry) -> None:
        """Lève `StoreError` si l'entrée est invalide (rien n'est écrit)."""
        ...

    async def list_for_project(
        self,
        project_id: UUID,
        limit: int = 200,
        *,
        execution_id: UUID | None = None,
        step_seq: int | None = None,
        newest_first: bool = False,
    ) -> list[AuditEntry]: ...


@dataclass(frozen=True, slots=True)
class Stores:
    plans: PlanStore
    executions: ExecutionStore
    registry: ResourceRegistry
    audit: AuditLog
