"""Assemblage des dépôts PostgreSQL."""

from sqlalchemy.ext.asyncio import AsyncEngine

from foreman.core.store import Stores
from foreman.infra.db.audit import PostgresAuditLog
from foreman.infra.db.executions import PostgresExecutionStore
from foreman.infra.db.plans import PostgresPlanStore
from foreman.infra.db.registry import PostgresResourceRegistry


def postgres_stores(engine: AsyncEngine) -> Stores:
    return Stores(
        plans=PostgresPlanStore(engine),
        executions=PostgresExecutionStore(engine),
        registry=PostgresResourceRegistry(engine),
        audit=PostgresAuditLog(engine),
    )
