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
ROLES = ("developer", "team_admin", "org_admin")
PROJECT_STATUSES = ("draft", "active", "archived")
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
    sa.Column("password_hash", sa.Text, nullable=True),
    sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    sa.Index("uq_users_email_lower", sa.func.lower(sa.column("email")), unique=True),
)

# Rôle par équipe, synchronisé au démarrage depuis FOREMAN_DEV_MEMBERS (voir infra/db/members.py).
memberships = sa.Table(
    "memberships",
    metadata,
    sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
    sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), primary_key=True),
    sa.Column("role", sa.Text, nullable=False),
    sa.CheckConstraint(_in("role", ROLES), name="memberships_role"),
)

teams = sa.Table(
    "teams",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("name", sa.Text, nullable=False, unique=True),
    sa.Column(
        "admin_approval_required", sa.Boolean, nullable=False, server_default=sa.text("true")
    ),
    sa.Column("personal", sa.Boolean, nullable=False, server_default=sa.text("false")),
)

# Seuls les condensats entrent en base (jeton de session, CSRF, jeton d'invitation).
sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id_hash", sa.Text, primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("csrf_hash", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_sessions_user_id", "user_id"),
)

invitations = sa.Table(
    "invitations",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("token_hash", sa.Text, nullable=False, unique=True),
    sa.Column("email", sa.Text, nullable=False),
    sa.Column("team_id", UUID(as_uuid=True), sa.ForeignKey("teams.id"), nullable=True),
    sa.Column("role", sa.Text, nullable=False),
    sa.Column("invited_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(_in("role", ROLES), name="invitations_role"),
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
    # Dernier `seq` attribué dans `project_events` (0 = aucun événement) : voir infra/db/events.py.
    sa.Column("last_event_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
    sa.UniqueConstraint("team_id", "slug"),
    sa.CheckConstraint("char_length(name) <= 120", name="projects_name_len"),
    sa.CheckConstraint(_in("status", PROJECT_STATUSES), name="projects_status"),
    sa.Index("ix_projects_created_at_desc", sa.text("created_at DESC")),
)

# Journal d'événements du chat (contrat figé v1) : `data` est la charge utile telle qu'émise.
project_events = sa.Table(
    "project_events",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("turn_id", UUID(as_uuid=True), nullable=False),
    sa.Column("type", sa.Text, nullable=False),
    sa.Column("data", JSONB, nullable=False),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("project_id", "seq"),
    sa.CheckConstraint("seq > 0", name="project_events_seq"),
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
    # `{reason, changes}` : présent si et seulement si le plan est `invalidated` (migration 0005).
    sa.Column("invalidation", JSONB, nullable=True),
    sa.UniqueConstraint("project_id", "version"),
    sa.UniqueConstraint("id", "content_hash"),
    sa.UniqueConstraint("id", "project_id"),
    sa.CheckConstraint("version >= 1", name="plans_version"),
    sa.CheckConstraint(_in("status", PLAN_STATUSES), name="plans_status"),
    sa.CheckConstraint(
        "(status = 'invalidated') = (invalidation IS NOT NULL)", name="plans_invalidation"
    ),
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
    sa.Column("environment", sa.Text, nullable=False),
    sa.Column("checkpoint", JSONB(none_as_null=True), nullable=True),
    sa.Column("budget_used", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("lease_owner", sa.Text, nullable=True),
    sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("lease_epoch", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("id", "project_id"),
    sa.ForeignKeyConstraint(["plan_id", "project_id"], ["plans.id", "plans.project_id"]),
    sa.CheckConstraint("lease_epoch >= 0", name="executions_lease_epoch"),
    sa.CheckConstraint(_in("state", EXECUTION_STATES), name="executions_state"),
    sa.CheckConstraint("autonomy_level BETWEEN 1 AND 4", name="executions_autonomy_level"),
    # D8 : jamais d'autonomie totale en production, même si le code se trompe.
    sa.CheckConstraint(
        "environment <> 'production' OR autonomy_level <= 3", name="executions_production_autonomy"
    ),
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
    sa.Column("execution_id", UUID(as_uuid=True), nullable=False),
    sa.Column("project_id", UUID(as_uuid=True), nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("tool", sa.Text, nullable=False),
    sa.Column("params", JSONB, nullable=False),
    sa.Column("idempotency_key", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
    sa.Column("result", JSONB(none_as_null=True), nullable=True),
    sa.Column("error", JSONB(none_as_null=True), nullable=True),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("execution_id", "seq"),
    sa.UniqueConstraint("id", "project_id"),
    sa.ForeignKeyConstraint(
        ["execution_id", "project_id"], ["executions.id", "executions.project_id"]
    ),
    sa.CheckConstraint(_in("status", STEP_STATUSES), name="execution_steps_status"),
)

step_idempotency = sa.Table(
    "step_idempotency",
    metadata,
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), primary_key=True),
    sa.Column("key", sa.Text, primary_key=True),
    sa.Column("step_id", UUID(as_uuid=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'reserved'")),
    sa.Column("result", JSONB(none_as_null=True), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.ForeignKeyConstraint(
        ["step_id", "project_id"], ["execution_steps.id", "execution_steps.project_id"]
    ),
    sa.CheckConstraint("status IN ('reserved','done')", name="step_idempotency_status"),
    sa.CheckConstraint("status = 'reserved' OR result IS NOT NULL", name="step_idempotency_result"),
)

managed_resources = sa.Table(
    "managed_resources",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=_UUID_DEFAULT),
    sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
    sa.Column("execution_id", UUID(as_uuid=True), nullable=True),
    sa.Column("step_id", UUID(as_uuid=True), nullable=True),
    sa.Column("provider", sa.Text, nullable=False),
    sa.Column("resource_type", sa.Text, nullable=False),
    sa.Column("external_id", sa.Text, nullable=False),
    sa.Column("external_url", sa.Text, nullable=True),
    sa.Column("origin", sa.Text, nullable=False, server_default=sa.text("'created'")),
    sa.Column("adopted_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    sa.UniqueConstraint("provider", "resource_type", "external_id"),
    sa.UniqueConstraint("id", "project_id"),
    sa.ForeignKeyConstraint(
        ["execution_id", "project_id"], ["executions.id", "executions.project_id"]
    ),
    sa.ForeignKeyConstraint(
        ["step_id", "project_id"], ["execution_steps.id", "execution_steps.project_id"]
    ),
    sa.CheckConstraint("origin IN ('created','adopted')", name="managed_resources_origin"),
    sa.Index("ix_managed_resources_project_id", "project_id"),
)

observed_state = sa.Table(
    "observed_state",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
    sa.Column("resource_id", UUID(as_uuid=True), nullable=False),
    sa.Column("project_id", UUID(as_uuid=True), nullable=False),
    sa.Column("observed", JSONB, nullable=False),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.ForeignKeyConstraint(
        ["resource_id", "project_id"], ["managed_resources.id", "managed_resources.project_id"]
    ),
)

audit_events = sa.Table(
    "audit_events",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
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
    sa.Column("params_redacted", JSONB(none_as_null=True), nullable=True),
    sa.Column("result_redacted", JSONB(none_as_null=True), nullable=True),
    sa.Column("duration_ms", sa.Integer, nullable=True),
)

# Secrets chiffrés (AES-256-GCM, migration 0007) : jamais de texte clair ; `key_id` = clé maître.
secrets = sa.Table(
    "secrets",
    metadata,
    sa.Column("id", sa.Text, primary_key=True),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("key_id", sa.Text, nullable=False),
    sa.Column("nonce", sa.LargeBinary, nullable=False),
    sa.Column("ciphertext", sa.LargeBinary, nullable=False),
    sa.Column("created_by", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
)

# Statut des sondes d'un connecteur (migration 0008) : jamais de jeton, seulement des références.
connectors = sa.Table(
    "connectors",
    metadata,
    sa.Column(
        "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    ),
    sa.Column("provider", sa.Text, nullable=False, unique=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="incomplete"),
    sa.Column("declared_scopes", JSONB, nullable=False),
    sa.Column("verified_scopes", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    sa.Column("read_secret_ref", sa.Text, nullable=True),
    sa.Column("write_secret_ref", sa.Text, nullable=True),
    sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('ok', 'incomplete', 'revoked')", name="connectors_status_check"),
)
