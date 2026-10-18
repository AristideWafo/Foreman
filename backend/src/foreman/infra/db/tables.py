"""Schéma PostgreSQL (SQLAlchemy Core), identique aux migrations (test d'autogénération)."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData()

_UUID_DEFAULT = sa.text("gen_random_uuid()")
_NOW = sa.text("now()")

PLAN_STATUSES = ("proposed", "dev_approved", "admin_approved", "invalidated", "expired", "executed")
EXECUTION_STATES = (
    "running",
    "awaiting_permission",
    "awaiting_remediation",
    "succeeded",
    "partial",
    "failed_compensated",
    "blocked",
    "degraded",
)
ACTIVE_EXECUTION_STATES = ("running", "awaiting_permission", "awaiting_remediation")
STEP_STATUSES = ("pending", "running", "succeeded", "failed", "compensated", "skipped")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


users = sa.Table(
    "users",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("email", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
)

teams = sa.Table(
    "teams",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("name", sa.Text, nullable=False, unique=True),
    sa.Column(
        "admin_approval_required", sa.Boolean, nullable=False, server_default=sa.text("true")
    ),
)

projects = sa.Table(
    "projects",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=False),
    sa.Column("name", sa.Text, nullable=False, server_default=sa.text("''")),
    sa.Column("slug", sa.Text, nullable=True),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'draft'")),
    sa.Column("stack", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("open_questions", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("locked_reason", sa.Text, nullable=True),
    sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.UniqueConstraint("team_id", "slug"),
    sa.CheckConstraint("char_length(name) <= 120", name="projects_name_len"),
)

plans = sa.Table(
    "plans",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("content", JSONB, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("skills_used", JSONB, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'proposed'")),
    sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("project_id", "version"),
    sa.UniqueConstraint("id", "content_hash"),
    sa.UniqueConstraint("id", "project_id"),
    sa.CheckConstraint(_in("status", PLAN_STATUSES), name="plans_status"),
)

approvals = sa.Table(
    "approvals",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("plan_id", UUID(as_uuid=True), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("approver_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("decision", sa.Text, nullable=False),
    sa.Column("plan_hash", sa.Text, nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
    sa.ForeignKeyConstraint(["plan_id", "plan_hash"], ["plans.id", "plans.content_hash"]),
    sa.CheckConstraint(
        "kind IN ('developer','admin','remediation','adoption','command')", name="approvals_kind"
    ),
    sa.CheckConstraint("decision IN ('approved','rejected')", name="approvals_decision"),
    sa.Index(
        "uq_approvals_plan_kind_approved",
        "plan_id",
        "kind",
        unique=True,
        postgresql_where=sa.text("decision = 'approved'"),
    ),
)

executions = sa.Table(
    "executions",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("plan_id", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("project_id", UUID(as_uuid=True), nullable=False),
    sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'running'")),
    sa.Column("autonomy_level", sa.Integer, nullable=False),
    sa.Column("checkpoint", JSONB, nullable=True),
    sa.Column("budget_used", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("lease_owner", sa.Text, nullable=True),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("lease_epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(["plan_id", "project_id"], ["plans.id", "plans.project_id"]),
    sa.CheckConstraint(_in("state", EXECUTION_STATES), name="executions_state"),
    sa.Index(
        "uq_executions_one_active_per_project",
        "project_id",
        unique=True,
        postgresql_where=sa.text(_in("state", ACTIVE_EXECUTION_STATES)),
    ),
)

execution_steps = sa.Table(
    "execution_steps",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("tool", sa.Text, nullable=False),
    sa.Column("params", JSONB, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
    sa.Column("result", JSONB, nullable=True),
    sa.Column("error", JSONB, nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("execution_id", "seq"),
    sa.CheckConstraint(_in("status", STEP_STATUSES), name="execution_steps_status"),
)

step_idempotency = sa.Table(
    "step_idempotency",
    metadata,
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), primary_key=True),
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("execution_steps.id"), nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'reserved'")),
    sa.Column("result", JSONB, nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.CheckConstraint("status IN ('reserved','done')", name="step_idempotency_status"),
)

managed_resources = sa.Table(
    "managed_resources",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
    sa.Column("execution_id", UUID(as_uuid=True), sa.ForeignKey("executions.id"), nullable=True),
    sa.Column("step_id", UUID(as_uuid=True), sa.ForeignKey("execution_steps.id"), nullable=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("resource_type", sa.Text, nullable=False),
    sa.Column("external_id", sa.Text, nullable=False),
    sa.Column("external_url", sa.Text, nullable=True),
    sa.Column("origin", sa.Text, nullable=False, server_default=sa.text("'created'")),
    sa.Column("adopted_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("provider", "resource_type", "external_id"),
    sa.CheckConstraint("origin IN ('created','adopted')", name="managed_resources_origin"),
    sa.Index("ix_managed_resources_project_id", "project_id"),
)

observed_state = sa.Table(
    "observed_state",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column(
        "resource_id", UUID(as_uuid=True), sa.ForeignKey("managed_resources.id"), nullable=False
    ),
    sa.Column("observed", JSONB, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("project_id", UUID(as_uuid=True), nullable=True),
    sa.Column("plan_id", UUID(as_uuid=True), nullable=True),
    sa.Column("execution_id", UUID(as_uuid=True), nullable=True),
    sa.Column("step_seq", sa.Integer, nullable=True),
    sa.Column("plan_hash", sa.Text, nullable=True),
    sa.Column("actor_kind", sa.Text, nullable=False),
    sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
    sa.Column("actor", sa.Text, nullable=True),
    sa.Column("tool", sa.Text, nullable=True),
    sa.Column("tool_class", sa.Text, nullable=True),
    sa.Column("decision", sa.Text, nullable=True),
    sa.Column("rule_id", sa.Text, nullable=True),
    sa.Column("params_redacted", JSONB, nullable=True),
    sa.Column("result_redacted", JSONB, nullable=True),
    sa.Column("duration_ms", sa.Integer, nullable=True),
)
