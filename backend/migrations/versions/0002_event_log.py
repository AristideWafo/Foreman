"""Journal d'événements persisté : `project_events`, `projects.last_event_seq`, index de liste.

Écrit en SQL, comme 0001. Sur une base en service : `ADD COLUMN ... DEFAULT 0` ne réécrit pas la
table (PostgreSQL 11+), `project_events` est neuve, l'index porte sur au plus quelques centaines
de projets : aucun verrou long, aucune donnée à remplir (l'historique du chat n'existait qu'en
mémoire). Les projets existants repartent à `last_event_seq = 0`.

Retour arrière : `downgrade()` supprime le journal du chat ; il est refusé s'il contient des
événements, sauf accord explicite (même garde que 0001). Restaurer le `pg_dump` pris avant le
déploiement reste la voie normale.

Revision ID: 0002
Revises: 0001
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from foreman.config.env import ENV_ALLOW_DESTRUCTIVE_DOWNGRADE

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATEMENTS = (
    "ALTER TABLE projects ADD COLUMN last_event_seq int NOT NULL DEFAULT 0",
    # (project_id, seq) est la clé naturelle : lecture `seq > n` et élagage passent par son index
    """
    CREATE TABLE project_events (
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      project_id uuid NOT NULL REFERENCES projects(id),
      seq int NOT NULL,
      turn_id uuid NOT NULL,
      type text NOT NULL,
      data jsonb NOT NULL,
      at timestamptz NOT NULL,
      UNIQUE (project_id, seq),
      CONSTRAINT project_events_seq CHECK (seq > 0)
    )
    """,
    "CREATE INDEX ix_projects_created_at_desc ON projects (created_at DESC)",
)


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    # Le retour arrière supprime l'historique du chat : refusé s'il existe, sauf accord explicite
    # (bases de test, ou décision humaine d'exploitation après sauvegarde).
    has_events = (
        op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM project_events)")).scalar()
    )
    if has_events and os.environ.get(ENV_ALLOW_DESTRUCTIVE_DOWNGRADE) != "1":
        raise RuntimeError(
            f"project_events contient des données : retour arrière refusé "
            f"({ENV_ALLOW_DESTRUCTIVE_DOWNGRADE}=1 pour le forcer)"
        )
    op.execute("DROP INDEX IF EXISTS ix_projects_created_at_desc")
    op.execute("DROP TABLE IF EXISTS project_events")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS last_event_seq")
