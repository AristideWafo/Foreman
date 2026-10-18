"""Plans et approbations en PostgreSQL. Toutes les lectures sont cloisonnées par projet."""

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from foreman.core.store import (
    ApprovalRefused,
    ApprovalResult,
    Approved,
    NewPlan,
    PlanRecord,
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
                        )
                        .returning(*t.plans.c)
                    )
                ).one()
        except DBAPIError as exc:
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
        except DBAPIError as exc:
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
    ) -> ApprovalResult:
        try:
            async with self._engine.begin() as conn:
                return await self._approve(
                    conn, project_id, plan_id, plan_hash, approver_id, autonomy_level
                )
        except IntegrityError as exc:
            if constraint_of(exc) == ONE_ACTIVE_PER_PROJECT:
                return ApprovalRefused("execution_in_progress")  # la transaction est annulée
            log_failure("plan.approve", exc)
            raise StoreError("stockage indisponible") from None
        except DBAPIError as exc:
            log_failure("plan.approve", exc)
            raise StoreError("stockage indisponible") from None

    @staticmethod
    async def _approve(
        conn: AsyncConnection,
        project_id: UUID,
        plan_id: UUID,
        plan_hash: str,
        approver_id: UUID,
        autonomy_level: int,
    ) -> ApprovalResult:
        # Le verrou de la ligne sérialise les approbations concurrentes du même plan.
        plan = (
            await conn.execute(
                sa.select(*t.plans.c)
                .where(t.plans.c.id == plan_id, t.plans.c.project_id == project_id)
                .with_for_update()
            )
        ).one_or_none()
        if plan is None:
            return ApprovalRefused("not_found")
        if plan.content_hash != plan_hash:
            return ApprovalRefused("plan_hash_mismatch")
        if plan.status == "dev_approved":
            return await _existing_approval(conn, plan_id)
        updated = await conn.execute(
            sa.update(t.plans)
            .where(
                t.plans.c.id == plan_id,
                t.plans.c.status == "proposed",
                t.plans.c.expires_at > sa.func.now(),
            )
            .values(status="dev_approved")
            .returning(t.plans.c.id)
        )
        if updated.one_or_none() is None:
            return ApprovalRefused("plan_not_approvable")
        approval_id = (
            await conn.execute(
                sa.insert(t.approvals)
                .values(
                    plan_id=plan_id,
                    kind="developer",
                    approver_id=approver_id,
                    decision="approved",
                    plan_hash=plan_hash,
                )
                .returning(t.approvals.c.id)
            )
        ).scalar_one()
        execution_id = (
            await conn.execute(
                sa.insert(t.executions)
                .values(plan_id=plan_id, project_id=project_id, autonomy_level=autonomy_level)
                .returning(t.executions.c.id)
            )
        ).scalar_one()
        steps = steps_of(plan.content)
        if steps:
            await conn.execute(
                sa.insert(t.execution_steps),
                [
                    {
                        "execution_id": execution_id,
                        "seq": s.seq,
                        "tool": s.tool,
                        "params": dict(s.params),
                        "idempotency_key": s.idempotency_key,
                    }
                    for s in steps
                ],
            )
        return Approved(approval_id, execution_id, created=True)


async def _existing_approval(conn: AsyncConnection, plan_id: UUID) -> ApprovalResult:
    row = (
        await conn.execute(
            sa.select(
                t.approvals.c.id.label("approval_id"), t.executions.c.id.label("execution_id")
            )
            .select_from(
                t.approvals.join(t.executions, t.executions.c.plan_id == t.approvals.c.plan_id)
            )
            .where(t.approvals.c.plan_id == plan_id, t.approvals.c.decision == "approved")
            .order_by(t.approvals.c.decided_at)
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return ApprovalRefused("plan_not_approvable")
    return Approved(row.approval_id, row.execution_id, created=False)
