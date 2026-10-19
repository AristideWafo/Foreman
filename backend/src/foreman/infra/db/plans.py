"""Plans et approbations en PostgreSQL. Toutes les lectures sont cloisonnées par projet."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from foreman.core.store import (
    ADMIN_ROLES,
    AdminApprovalResult,
    AdminRejectionResult,
    ApprovalRefused,
    ApprovalResult,
    Approved,
    AwaitingAdmin,
    NewPlan,
    PlanRecord,
    Rejected,
    StoreError,
    UnknownProject,
    steps_of,
)
from foreman.infra.db import tables as t
from foreman.infra.db.engine import constraint_of, log_failure

ONE_ACTIVE_PER_PROJECT = "uq_executions_one_active_per_project"


def plan_record(row: Any) -> PlanRecord:
    return PlanRecord(
        id=row.id,
        project_id=row.project_id,
        version=row.version,
        content=row.content,
        content_hash=row.content_hash,
        skills_used=row.skills_used,
        status=row.status,
        created_at=row.created_at,
        expires_at=row.expires_at,
        requested_by=row.requested_by,
    )


class PostgresPlanStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, plan: NewPlan) -> PlanRecord:
        steps_of(plan.content)  # contenu valide avant toute écriture
        try:
            async with self._engine.begin() as conn:
                # Le verrou du projet sérialise l'attribution des versions.
                locked = await conn.execute(
                    sa.select(t.projects.c.id)
                    .where(t.projects.c.id == plan.project_id)
                    .with_for_update()
                )
                if locked.one_or_none() is None:
                    raise UnknownProject
                next_version = (
                    sa.select(sa.func.coalesce(sa.func.max(t.plans.c.version), 0) + 1)
                    .where(t.plans.c.project_id == plan.project_id)
                    .scalar_subquery()
                )
                row = (
                    await conn.execute(
                        sa.insert(t.plans)
                        .values(
                            project_id=plan.project_id,
                            version=next_version,
                            content=dict(plan.content),
                            content_hash=plan.content_hash,
                            skills_used=list(plan.skills_used),
                            expires_at=plan.expires_at,
                            requested_by=plan.requested_by,
                        )
                        .returning(*t.plans.c)
                    )
                ).one()
        except SQLAlchemyError as exc:
            log_failure("plan.create", exc)
            raise StoreError("stockage indisponible") from None
        return plan_record(row)

    async def get(self, project_id: UUID, plan_id: UUID) -> PlanRecord | None:
        statement = sa.select(*t.plans.c).where(
            t.plans.c.id == plan_id, t.plans.c.project_id == project_id
        )
        try:
            async with self._engine.connect() as conn:
                row = (await conn.execute(statement)).one_or_none()
        except SQLAlchemyError as exc:
            log_failure("plan.get", exc)
            raise StoreError("stockage indisponible") from None
        return None if row is None else plan_record(row)

    async def approve(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        autonomy_level: int,
        start_execution: bool = True,
    ) -> ApprovalResult:
        async def work(conn: AsyncConnection) -> ApprovalResult:
            plan = await _locked_plan(conn, project_id, plan_id)
            if plan is None:
                return ApprovalRefused("not_found")
            if plan.content_hash != plan_hash:
                return ApprovalRefused("plan_hash_mismatch")
            if plan.status == "dev_approved":
                return await _existing_approval(conn, plan_id)
            if plan.status != "proposed" or plan.expired:
                return ApprovalRefused("plan_not_approvable")
            await conn.execute(
                sa.update(t.plans).where(t.plans.c.id == plan_id).values(status="dev_approved")
            )
            approval_id = await _insert_approval(
                conn, plan_id, plan_hash, "developer", approver_id, "approved"
            )
            if not start_execution:
                return AwaitingAdmin(approval_id, created=True)
            execution_id = await _start_execution(conn, plan, autonomy_level)
            return Approved(approval_id, execution_id, created=True)

        return await self._transaction("plan.approve", work)

    async def approve_admin(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        approver_role: str,
        autonomy_level: int,
    ) -> AdminApprovalResult:
        if approver_role not in ADMIN_ROLES:
            return ApprovalRefused("forbidden")

        async def work(conn: AsyncConnection) -> AdminApprovalResult:
            plan = await _locked_plan(conn, project_id, plan_id)
            if plan is None:
                return ApprovalRefused("not_found")
            if plan.content_hash != plan_hash:
                return ApprovalRefused("plan_hash_mismatch")
            admin_id = await _decision_id(conn, plan_id, "admin", "approved")
            execution_id = await _execution_id(conn, plan_id)
            if admin_id and execution_id:
                return Approved(admin_id, execution_id, created=False)
            if plan.status != "dev_approved" or execution_id or plan.expired:
                return ApprovalRefused("plan_not_approvable")
            approval_id = await _insert_approval(
                conn, plan_id, plan_hash, "admin", approver_id, "approved"
            )
            return Approved(
                approval_id, await _start_execution(conn, plan, autonomy_level), created=True
            )

        return await self._transaction("plan.approve_admin", work)

    async def reject_admin(
        self,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        approver_role: str,
    ) -> AdminRejectionResult:
        if approver_role not in ADMIN_ROLES:
            return ApprovalRefused("forbidden")

        async def work(conn: AsyncConnection) -> AdminRejectionResult:
            plan = await _locked_plan(conn, project_id, plan_id)
            if plan is None:
                return ApprovalRefused("not_found")
            if plan.content_hash != plan_hash:
                return ApprovalRefused("plan_hash_mismatch")
            rejected_id = await _decision_id(conn, plan_id, "admin", "rejected")
            if rejected_id:
                return Rejected(rejected_id, created=False)
            if plan.status != "dev_approved" or await _execution_id(conn, plan_id):
                return ApprovalRefused("plan_not_approvable")
            await conn.execute(
                sa.update(t.plans).where(t.plans.c.id == plan_id).values(status="invalidated")
            )
            approval_id = await _insert_approval(
                conn, plan_id, plan_hash, "admin", approver_id, "rejected"
            )
            return Rejected(approval_id, created=True)

        return await self._transaction("plan.reject_admin", work)

    async def has_admin_approval(self, plan_id: UUID, plan_hash: str) -> bool:
        statement = sa.select(t.approvals.c.id).where(
            t.approvals.c.plan_id == plan_id,
            t.approvals.c.plan_hash == plan_hash,
            t.approvals.c.kind == "admin",
            t.approvals.c.decision == "approved",
        )
        try:
            async with self._engine.connect() as conn:
                return (await conn.execute(statement)).first() is not None
        except SQLAlchemyError as exc:
            log_failure("plan.has_admin_approval", exc)
            raise StoreError("stockage indisponible") from None

    async def _transaction[R](
        self, name: str, work: Callable[[AsyncConnection], Awaitable[R]]
    ) -> R | ApprovalRefused:
        """Une transaction ; un second plan actif du projet l'annule (`execution_in_progress`)."""
        try:
            async with self._engine.begin() as conn:
                return await work(conn)
        except IntegrityError as exc:
            if constraint_of(exc) == ONE_ACTIVE_PER_PROJECT:
                return ApprovalRefused("execution_in_progress")  # la transaction est annulée
            log_failure(name, exc)
            raise StoreError("stockage indisponible") from None
        except SQLAlchemyError as exc:
            log_failure(name, exc)
            raise StoreError("stockage indisponible") from None


async def _locked_plan(conn: AsyncConnection, project_id: UUID, plan_id: UUID) -> Any:
    """Le plan verrouillé (sérialise les décisions), avec `expired` calculé par la base."""
    return (
        await conn.execute(
            sa.select(*t.plans.c, (t.plans.c.expires_at <= sa.func.now()).label("expired"))
            .where(t.plans.c.id == plan_id, t.plans.c.project_id == project_id)
            .with_for_update()
        )
    ).one_or_none()


async def _insert_approval(
    conn: AsyncConnection,
    plan_id: UUID,
    plan_hash: str,
    kind: str,
    approver_id: UUID,
    decision: str,
) -> UUID:
    approval_id: UUID = (
        await conn.execute(
            sa.insert(t.approvals)
            .values(
                plan_id=plan_id,
                kind=kind,
                approver_id=approver_id,
                decision=decision,
                plan_hash=plan_hash,
            )
            .returning(t.approvals.c.id)
        )
    ).scalar_one()
    return approval_id


async def _decision_id(
    conn: AsyncConnection, plan_id: UUID, kind: str, decision: str
) -> UUID | None:
    found: UUID | None = (
        await conn.execute(
            sa.select(t.approvals.c.id)
            .where(
                t.approvals.c.plan_id == plan_id,
                t.approvals.c.kind == kind,
                t.approvals.c.decision == decision,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return found


async def _execution_id(conn: AsyncConnection, plan_id: UUID) -> UUID | None:
    found: UUID | None = (
        await conn.execute(sa.select(t.executions.c.id).where(t.executions.c.plan_id == plan_id))
    ).scalar_one_or_none()
    return found


async def _start_execution(conn: AsyncConnection, plan: Any, autonomy_level: int) -> UUID:
    """Exécution et étapes `pending` du plan, dans la transaction de l'approbation."""
    execution_id = uuid4()  # connu avant l'insertion : il entre dans les clés d'idempotence
    await conn.execute(
        sa.insert(t.executions).values(
            id=execution_id,
            plan_id=plan.id,
            project_id=plan.project_id,
            autonomy_level=autonomy_level,
            # Copie du plan : la base refuse le niveau 4 en production (CHECK).
            environment=plan.content.get("environment"),
        )
    )
    steps = [s.bound_to(execution_id) for s in steps_of(plan.content)]
    if steps:
        await conn.execute(
            sa.insert(t.execution_steps),
            [
                {
                    "execution_id": execution_id,
                    "project_id": plan.project_id,
                    "seq": s.seq,
                    "tool": s.tool,
                    "params": dict(s.params),
                    "idempotency_key": s.idempotency_key,
                }
                for s in steps
            ],
        )
    return execution_id


async def _existing_approval(conn: AsyncConnection, plan_id: UUID) -> ApprovalResult:
    """Rejeu : le plan est déjà validé par le développeur (avec ou sans exécution)."""
    approval_id = await _decision_id(conn, plan_id, "developer", "approved")
    if approval_id is None:
        return ApprovalRefused("plan_not_approvable")
    execution_id = await _execution_id(conn, plan_id)
    if execution_id is None:
        return AwaitingAdmin(approval_id, created=False)
    return Approved(approval_id, execution_id, created=False)
