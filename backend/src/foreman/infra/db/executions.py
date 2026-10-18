"""Exécutions, bail, idempotence des étapes : tout passe par des requêtes paramétrées.

Le temps est celui de la base (`now()`), jamais celui de l'application. Chaque écriture d'étape ou
d'exécution revérifie le jeton de bail (`lease_epoch`) dans la même transaction.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from foreman.core.store import (
    LEASE_TTL_S,
    AuditEntry,
    CompletedReservation,
    DuplicateResource,
    ExecutionRecord,
    InvalidTransition,
    Lease,
    NewReservation,
    NewResource,
    OrphanReservation,
    Reservation,
    StaleLease,
    StepRecord,
    StoreError,
)
from foreman.infra.db import tables as t
from foreman.infra.db.audit import audit_values
from foreman.infra.db.engine import constraint_of, log_failure

_RESOURCE_UNIQUE_PREFIX = "managed_resources_provider"


def _step(row: Any) -> StepRecord:
    return StepRecord(
        id=row.id,
        seq=row.seq,
        tool=row.tool,
        params=row.params,
        idempotency_key=row.idempotency_key,
        status=row.status,
        result=row.result,
    )


async def _held(conn: AsyncConnection, lease: Lease) -> Any:
    """Verrouille l'exécution si le jeton est toujours le nôtre ; sinon `StaleLease`.

    Le verrou de ligne empêche une prise de bail concurrente pendant l'écriture.
    """
    row = (
        await conn.execute(
            sa.select(t.executions.c.state, t.executions.c.project_id, t.executions.c.plan_id)
            .where(
                t.executions.c.id == lease.execution_id,
                t.executions.c.lease_owner == lease.owner,
                t.executions.c.lease_epoch == lease.epoch,
            )
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise StaleLease
    return row


class PostgresExecutionStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get(self, project_id: UUID, execution_id: UUID) -> ExecutionRecord | None:
        try:
            async with self._engine.connect() as conn:
                execution = (
                    await conn.execute(
                        sa.select(*t.executions.c).where(
                            t.executions.c.id == execution_id,
                            t.executions.c.project_id == project_id,
                        )
                    )
                ).one_or_none()
                if execution is None:
                    return None
                steps = (
                    await conn.execute(
                        sa.select(*t.execution_steps.c)
                        .where(t.execution_steps.c.execution_id == execution_id)
                        .order_by(t.execution_steps.c.seq)
                    )
                ).all()
        except DBAPIError as exc:
            log_failure("execution.get", exc)
            raise StoreError("stockage indisponible") from None
        return ExecutionRecord(
            id=execution.id,
            plan_id=execution.plan_id,
            project_id=execution.project_id,
            state=execution.state,
            autonomy_level=execution.autonomy_level,
            steps=[_step(s) for s in steps],
        )

    async def claim_lease(
        self, execution_id: UUID, owner: str, ttl_s: int = LEASE_TTL_S
    ) -> Lease | None:
        statement = (
            sa.update(t.executions)
            .where(
                t.executions.c.id == execution_id,
                t.executions.c.state == "running",
                sa.or_(
                    t.executions.c.lease_owner.is_(None),
                    t.executions.c.lease_expires_at < sa.func.now(),
                    t.executions.c.lease_owner == owner,
                ),
            )
            .values(
                lease_owner=owner,
                lease_expires_at=sa.func.now()
                + sa.func.make_interval(0, 0, 0, 0, 0, 0, float(ttl_s)),
                lease_epoch=t.executions.c.lease_epoch + 1,
            )
            .returning(t.executions.c.lease_epoch)
        )
        try:
            async with self._engine.begin() as conn:
                epoch = (await conn.execute(statement)).scalar_one_or_none()
        except DBAPIError as exc:
            log_failure("execution.claim_lease", exc)
            raise StoreError("stockage indisponible") from None
        return None if epoch is None else Lease(execution_id, owner, epoch)

    async def renew(self, lease: Lease, ttl_s: int = LEASE_TTL_S) -> bool:
        statement = (
            sa.update(t.executions)
            .where(
                t.executions.c.id == lease.execution_id,
                t.executions.c.state == "running",
                t.executions.c.lease_owner == lease.owner,
                t.executions.c.lease_epoch == lease.epoch,
            )
            .values(
                lease_expires_at=sa.func.now()
                + sa.func.make_interval(0, 0, 0, 0, 0, 0, float(ttl_s))
            )
            .returning(t.executions.c.id)
        )
        try:
            async with self._engine.begin() as conn:
                return (await conn.execute(statement)).scalar_one_or_none() is not None
        except DBAPIError as exc:
            log_failure("execution.renew", exc)
            raise StoreError("stockage indisponible") from None

    async def next_step(self, execution_id: UUID) -> StepRecord | None:
        statement = (
            sa.select(*t.execution_steps.c)
            .where(
                t.execution_steps.c.execution_id == execution_id,
                t.execution_steps.c.status != "succeeded",
            )
            .order_by(t.execution_steps.c.seq)
            .limit(1)
        )
        try:
            async with self._engine.connect() as conn:
                row = (await conn.execute(statement)).one_or_none()
        except DBAPIError as exc:
            log_failure("execution.next_step", exc)
            raise StoreError("stockage indisponible") from None
        return None if row is None else _step(row)

    async def reserve_idempotency(self, lease: Lease, step_seq: int) -> Reservation:
        try:
            async with self._engine.begin() as conn:
                execution = await _held(conn, lease)
                step = (
                    await conn.execute(
                        sa.select(t.execution_steps.c.id, t.execution_steps.c.idempotency_key)
                        .where(
                            t.execution_steps.c.execution_id == lease.execution_id,
                            t.execution_steps.c.seq == step_seq,
                            t.execution_steps.c.status.in_(("pending", "running")),
                        )
                        .with_for_update()
                    )
                ).one_or_none()
                if execution.state != "running" or step is None:
                    raise InvalidTransition
                await conn.execute(
                    sa.update(t.execution_steps)
                    .where(
                        t.execution_steps.c.id == step.id, t.execution_steps.c.status == "pending"
                    )
                    .values(status="running", started_at=sa.func.now())
                )
                inserted = (
                    await conn.execute(
                        pg_insert(t.step_idempotency)
                        .values(
                            project_id=execution.project_id,
                            key=step.idempotency_key,
                            step_id=step.id,
                        )
                        .on_conflict_do_nothing()
                        .returning(t.step_idempotency.c.key)
                    )
                ).one_or_none()
                if inserted is not None:
                    return NewReservation()
                previous = (
                    await conn.execute(
                        sa.select(t.step_idempotency.c.status, t.step_idempotency.c.result).where(
                            t.step_idempotency.c.project_id == execution.project_id,
                            t.step_idempotency.c.key == step.idempotency_key,
                        )
                    )
                ).one()
                if previous.status == "done" and previous.result is not None:
                    return CompletedReservation(previous.result)
                return OrphanReservation()
        except DBAPIError as exc:
            log_failure("execution.reserve_idempotency", exc)
            raise StoreError("stockage indisponible") from None

    async def complete_step(
        self,
        lease: Lease,
        step_seq: int,
        result: Mapping[str, object],
        created_resources: Sequence[NewResource],
        audit: Sequence[AuditEntry],
    ) -> None:
        try:
            async with self._engine.begin() as conn:  # UNE transaction : tout ou rien
                execution = await _held(conn, lease)
                if execution.state != "running":
                    raise InvalidTransition
                step = (
                    await conn.execute(
                        sa.update(t.execution_steps)
                        .where(
                            t.execution_steps.c.execution_id == lease.execution_id,
                            t.execution_steps.c.seq == step_seq,
                            t.execution_steps.c.status == "running",
                        )
                        .values(status="succeeded", result=dict(result), finished_at=sa.func.now())
                        .returning(t.execution_steps.c.id, t.execution_steps.c.idempotency_key)
                    )
                ).one_or_none()
                if step is None:
                    raise InvalidTransition
                done = await conn.execute(
                    sa.update(t.step_idempotency)
                    .where(
                        t.step_idempotency.c.project_id == execution.project_id,
                        t.step_idempotency.c.key == step.idempotency_key,
                    )
                    .values(status="done", result=dict(result))
                    .returning(t.step_idempotency.c.key)
                )
                if done.one_or_none() is None:
                    raise InvalidTransition  # étape jamais réservée
                if created_resources:
                    await conn.execute(
                        sa.insert(t.managed_resources),
                        [
                            {
                                "project_id": execution.project_id,
                                "execution_id": lease.execution_id,
                                "step_id": step.id,
                                "provider": r.provider,
                                "resource_type": r.resource_type,
                                "external_id": r.external_id,
                                "external_url": r.external_url,
                            }
                            for r in created_resources
                        ],
                    )
                if audit:
                    await conn.execute(
                        sa.insert(t.audit_events), [audit_values(entry) for entry in audit]
                    )
        except IntegrityError as exc:
            if constraint_of(exc).startswith(_RESOURCE_UNIQUE_PREFIX):
                raise DuplicateResource from None
            log_failure("execution.complete_step", exc)
            raise StoreError("stockage indisponible") from None
        except DBAPIError as exc:
            log_failure("execution.complete_step", exc)
            raise StoreError("écriture refusée") from None

    async def finish(self, lease: Lease, state: Literal["succeeded", "blocked"]) -> None:
        try:
            async with self._engine.begin() as conn:
                execution = await _held(conn, lease)
                if execution.state != "running":
                    raise InvalidTransition
                await conn.execute(
                    sa.update(t.executions)
                    .where(
                        t.executions.c.id == lease.execution_id,
                        t.executions.c.lease_epoch == lease.epoch,
                    )
                    .values(state=state, finished_at=sa.func.now())
                )
                if state == "succeeded":
                    await conn.execute(
                        sa.update(t.plans)
                        .where(
                            t.plans.c.id == execution.plan_id, t.plans.c.status == "dev_approved"
                        )
                        .values(status="executed")
                    )
        except DBAPIError as exc:
            log_failure("execution.finish", exc)
            raise StoreError("stockage indisponible") from None
