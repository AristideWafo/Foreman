"""Schéma initial (scénario S1) : 11 tables, idempotence, bail, audit append-only.

Écrit en SQL pour rester lisible face à la spécification. Corrections du SQL de la spec : voir
`docs/plans/semaine-2.md`. Migration de base vide : aucun verrou long, aucune donnée à remplir.
Retour arrière : `downgrade()` supprime tout, journal d'audit compris (bases de test seulement).

Revision ID: 0001
Revises:
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foreman.config.env import ENV_ALLOW_DESTRUCTIVE_DOWNGRADE

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    # Identités et équipes (minimales ; insérées au démarrage)
    """
    CREATE TABLE users (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      email text UNIQUE NOT NULL,
      name text NOT NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE teams (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      name text UNIQUE NOT NULL,
      admin_approval_required boolean NOT NULL DEFAULT true
    )
    """,
    # slug nullable : un projet est créé sans titre, le plan fixe le slug
    """
    CREATE TABLE projects (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      team_id uuid NOT NULL REFERENCES teams(id),
      name text NOT NULL DEFAULT '',
      slug text,
      status text NOT NULL DEFAULT 'draft',
      stack jsonb NOT NULL DEFAULT '{}'::jsonb,
      open_questions jsonb NOT NULL DEFAULT '[]'::jsonb,
      locked_reason text,
      created_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE (team_id, slug),
      CONSTRAINT projects_name_len CHECK (char_length(name) <= 120),
      CONSTRAINT projects_status CHECK (status IN ('draft','active','archived'))
    )
    """,
    # UNIQUE(id, content_hash) et UNIQUE(id, project_id) : cibles des clés étrangères composites
    """
    CREATE TABLE plans (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id uuid NOT NULL REFERENCES projects(id),
      version int NOT NULL,
      content jsonb NOT NULL,
      content_hash text NOT NULL,
      skills_used jsonb NOT NULL,
      status text NOT NULL DEFAULT 'proposed',
      requested_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      expires_at timestamptz NOT NULL,
      UNIQUE (project_id, version),
      UNIQUE (id, content_hash),
      UNIQUE (id, project_id),
      CONSTRAINT plans_version CHECK (version >= 1),
      CONSTRAINT plans_status CHECK (status IN
        ('proposed','dev_approved','admin_approved','invalidated','expired','executed'))
    )
    """,
    # L'approbation porte sur le hash : (plan_id, plan_hash) doit exister dans plans
    """
    CREATE TABLE approvals (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_id uuid NOT NULL REFERENCES plans(id),
      kind text NOT NULL,
      approver_id uuid NOT NULL REFERENCES users(id),
      decision text NOT NULL,
      plan_hash text NOT NULL,
      decided_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (plan_id, plan_hash) REFERENCES plans(id, content_hash),
      CONSTRAINT approvals_kind CHECK
        (kind IN ('developer','admin','remediation','adoption','command')),
      CONSTRAINT approvals_decision CHECK (decision IN ('approved','rejected'))
    )
    """,
    """
    CREATE UNIQUE INDEX uq_approvals_plan_kind_approved
      ON approvals (plan_id, kind) WHERE decision = 'approved'
    """,
    # Une exécution par plan, du même projet que lui (clé composite), une seule active par projet.
    # Pas d'état « awaiting_approval » : l'attente est portée par plans.status = 'proposed'.
    # lease_epoch : jeton de bail, incrémenté à chaque prise (écarte un worker périmé).
    """
    CREATE TABLE executions (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      plan_id uuid NOT NULL UNIQUE,
      project_id uuid NOT NULL,
      state text NOT NULL DEFAULT 'running',
      autonomy_level int NOT NULL,
      checkpoint jsonb,
      budget_used jsonb NOT NULL DEFAULT '{}'::jsonb,
      lease_owner text,
      lease_expires_at timestamptz,
      lease_epoch bigint NOT NULL DEFAULT 0,
      started_at timestamptz NOT NULL DEFAULT now(),
      finished_at timestamptz,
      UNIQUE (id, project_id),
      FOREIGN KEY (plan_id, project_id) REFERENCES plans(id, project_id),
      CONSTRAINT executions_lease_epoch CHECK (lease_epoch >= 0),
      CONSTRAINT executions_state CHECK (state IN ('running','awaiting_permission',
        'awaiting_remediation','succeeded','partial','failed_compensated','blocked','degraded'))
    )
    """,
    """
    CREATE UNIQUE INDEX uq_executions_one_active_per_project
      ON executions (project_id)
      WHERE state IN ('running','awaiting_permission','awaiting_remediation')
    """,
    # Étapes pré-insérées en 'pending' ; idempotency_key n'est plus unique (voir step_idempotency)
    """
    CREATE TABLE execution_steps (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      execution_id uuid NOT NULL,
      project_id uuid NOT NULL,
      seq int NOT NULL,
      tool text NOT NULL,
      params jsonb NOT NULL,
      idempotency_key text NOT NULL,
      status text NOT NULL DEFAULT 'pending',
      result jsonb,
      error jsonb,
      started_at timestamptz,
      finished_at timestamptz,
      UNIQUE (execution_id, seq),
      UNIQUE (id, project_id),
      FOREIGN KEY (execution_id, project_id) REFERENCES executions(id, project_id),
      CONSTRAINT execution_steps_status CHECK
        (status IN ('pending','running','succeeded','failed','compensated','skipped'))
    )
    """,
    # Réservation d'idempotence, portée par projet. 'reserved' sans résultat après une panne
    # n'est jamais rejoué à l'aveugle.
    """
    CREATE TABLE step_idempotency (
      project_id uuid NOT NULL REFERENCES projects(id),
      key text NOT NULL,
      step_id uuid NOT NULL,
      status text NOT NULL DEFAULT 'reserved',
      result jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (project_id, key),
      FOREIGN KEY (step_id, project_id) REFERENCES execution_steps(id, project_id),
      CONSTRAINT step_idempotency_status CHECK (status IN ('reserved','done')),
      CONSTRAINT step_idempotency_result CHECK (status = 'reserved' OR result IS NOT NULL)
    )
    """,
    """
    CREATE TABLE managed_resources (
      id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      project_id uuid NOT NULL REFERENCES projects(id),
      execution_id uuid,
      step_id uuid,
      provider text NOT NULL,
      resource_type text NOT NULL,
      external_id text NOT NULL,
      external_url text,
      origin text NOT NULL DEFAULT 'created',
      adopted_by uuid REFERENCES users(id),
      created_at timestamptz NOT NULL DEFAULT now(),
      deleted_at timestamptz,
      UNIQUE (provider, resource_type, external_id),
      UNIQUE (id, project_id),
      FOREIGN KEY (execution_id, project_id) REFERENCES executions(id, project_id),
      FOREIGN KEY (step_id, project_id) REFERENCES execution_steps(id, project_id),
      CONSTRAINT managed_resources_origin CHECK (origin IN ('created','adopted'))
    )
    """,
    "CREATE INDEX ix_managed_resources_project_id ON managed_resources (project_id)",
    # id : la spec n'avait pas de clé primaire
    """
    CREATE TABLE observed_state (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      resource_id uuid NOT NULL,
      project_id uuid NOT NULL,
      observed jsonb NOT NULL,
      observed_at timestamptz NOT NULL DEFAULT now(),
      FOREIGN KEY (resource_id, project_id) REFERENCES managed_resources(id, project_id)
    )
    """,
    # Pas de clé étrangère : le journal survit à tout. Colonnes de corrélation ajoutées.
    """
    CREATE TABLE audit_events (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      at timestamptz NOT NULL DEFAULT now(),
      project_id uuid,
      plan_id uuid,
      execution_id uuid,
      step_seq int,
      plan_hash text,
      actor_kind text NOT NULL,
      actor_id uuid,
      actor text,
      tool text,
      tool_class text,
      decision text,
      rule_id text,
      params_redacted jsonb,
      result_redacted jsonb,
      duration_ms int
    )
    """,
)

_FORBID_MUTATION = """
CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only';
END
$$ LANGUAGE plpgsql
"""

# Un plan est la chose approuvée : seuls `status` et `expires_at` peuvent changer.
_FORBID_PLAN_CHANGE = """
CREATE OR REPLACE FUNCTION forbid_plan_content_change() RETURNS trigger AS $$
BEGIN
  IF (NEW.id, NEW.project_id, NEW.version, NEW.content, NEW.content_hash, NEW.skills_used,
      NEW.requested_by, NEW.created_at)
     IS DISTINCT FROM
     (OLD.id, OLD.project_id, OLD.version, OLD.content, OLD.content_hash, OLD.skills_used,
      OLD.requested_by, OLD.created_at) THEN
    RAISE EXCEPTION 'plans content is immutable';
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql
"""

_PLAN_TRIGGER = """
CREATE TRIGGER plans_immutable_content BEFORE UPDATE ON plans
  FOR EACH ROW EXECUTE FUNCTION forbid_plan_content_change()
"""

# Un déclencheur de niveau ligne n'intercepte pas TRUNCATE : deux déclencheurs distincts.
_AUDIT_TRIGGERS = (
    """
    CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE ON audit_events
      FOR EACH ROW EXECUTE FUNCTION forbid_mutation()
    """,
    """
    CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON audit_events
      FOR EACH STATEMENT EXECUTE FUNCTION forbid_mutation()
    """,
)

_DROP_ORDER = (
    "observed_state",
    "managed_resources",
    "step_idempotency",
    "execution_steps",
    "executions",
    "approvals",
    "plans",
    "projects",
    "teams",
    "users",
    "audit_events",
)


def upgrade() -> None:
    for statement in _TABLES:
        op.execute(statement)
    op.execute(_FORBID_MUTATION)
    for statement in _AUDIT_TRIGGERS:
        op.execute(statement)
    op.execute(_FORBID_PLAN_CHANGE)
    op.execute(_PLAN_TRIGGER)


def downgrade() -> None:
    # Le retour arrière supprime le journal d'audit : refusé s'il contient des données,
    # sauf accord explicite (bases de test, ou décision humaine d'exploitation).
    has_audit = (
        op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM audit_events)")).scalar()
    )
    if has_audit and os.environ.get(ENV_ALLOW_DESTRUCTIVE_DOWNGRADE) != "1":
        raise RuntimeError(
            f"audit_events contient des données : retour arrière refusé "
            f"({ENV_ALLOW_DESTRUCTIVE_DOWNGRADE}=1 pour le forcer)"
        )
    op.execute("DROP TRIGGER IF EXISTS plans_immutable_content ON plans")
    op.execute("DROP TRIGGER IF EXISTS audit_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_append_only ON audit_events")
    for table in _DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP FUNCTION IF EXISTS forbid_mutation()")
    op.execute("DROP FUNCTION IF EXISTS forbid_plan_content_change()")
