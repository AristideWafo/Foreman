"""Rôles (`memberships`) et plafond d'autonomie (`executions.environment`, deux CHECK).

Écrit en SQL, comme 0001 et 0002. Zone sensible, relue par le propriétaire.

- `memberships` est neuve (vide) : elle est remplie au démarrage depuis FOREMAN_DEV_MEMBERS.
- `executions.environment` : ajoutée NULLABLE, remplie depuis `plans.content->>'environment'`,
  puis NOT NULL. Une exécution dont le plan n'a pas d'environnement (plans d'avant la S2) est
  rattachée à `staging` : c'était alors le seul environnement approuvable, la production étant
  refusée à l'approbation.
- Les deux CHECK valident les lignes existantes : si une exécution viole la règle (niveau hors
  1 à 4, ou niveau 4 en production), la migration ÉCHOUE et rien n'est modifié (DDL transactionnel
  PostgreSQL). Aucune ligne n'est corrigée en silence.
- Verrous : tables de quelques dizaines de lignes, ALTER TABLE brefs.

Retour arrière : supprime les CHECK, la colonne `environment` (dérivable de `plans.content`) et
`memberships` (reconstruite au démarrage depuis l'environnement). Aucune donnée d'audit, de plan
ou d'exécution n'est détruite : pas de garde `FOREMAN_ALLOW_DESTRUCTIVE_DOWNGRADE`.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE = (
    """
    CREATE TABLE memberships (
      user_id uuid NOT NULL REFERENCES users(id),
      team_id uuid NOT NULL REFERENCES teams(id),
      role text NOT NULL,
      PRIMARY KEY (user_id, team_id),
      CONSTRAINT memberships_role CHECK (role IN ('developer', 'team_admin', 'org_admin'))
    )
    """,
    "ALTER TABLE executions ADD COLUMN environment text",
    """
    UPDATE executions e
    SET environment = COALESCE(p.content ->> 'environment', 'staging')
    FROM plans p
    WHERE p.id = e.plan_id
    """,
    "ALTER TABLE executions ALTER COLUMN environment SET NOT NULL",
    "ALTER TABLE executions ADD CONSTRAINT executions_autonomy_level "
    "CHECK (autonomy_level BETWEEN 1 AND 4)",
    "ALTER TABLE executions ADD CONSTRAINT executions_production_autonomy "
    "CHECK (environment <> 'production' OR autonomy_level <= 3)",
)

_DOWNGRADE = (
    "ALTER TABLE executions DROP CONSTRAINT IF EXISTS executions_production_autonomy",
    "ALTER TABLE executions DROP CONSTRAINT IF EXISTS executions_autonomy_level",
    "ALTER TABLE executions DROP COLUMN IF EXISTS environment",
    "DROP TABLE IF EXISTS memberships",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
