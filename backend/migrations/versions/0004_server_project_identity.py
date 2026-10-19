"""Identité des `server_project` : `environnement/slug` au lieu du seul slug (#177).

Zone sensible, à relire. Faire un `pg_dump` avant le déploiement.

- Upgrade : réécrit `managed_resources.external_id` des lignes `server_project` rattachées à une
  exécution, en `<executions.environment>/<slug>`. Les lignes sans exécution (adoptées) ne portent
  aucun environnement connu : elles sont laissées telles quelles. Idempotent (les lignes déjà au
  format `env/slug` sont ignorées). L'unicité globale (provider, resource_type, external_id) ne
  change pas ; elle ne peut pas être violée, le préfixe distinguant les environnements.
- Downgrade : retire le préfixe. ÉCHOUE (contrainte d'unicité, rien n'est modifié) si le même slug
  existe en staging et en production : aucune ligne n'est écrasée en silence.
- Verrous : UPDATE sur une table de quelques lignes, bref.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE managed_resources m
        SET external_id = e.environment || '/' || m.external_id
        FROM executions e
        WHERE e.id = m.execution_id AND e.project_id = m.project_id
          AND m.resource_type = 'server_project'
          AND m.external_id NOT LIKE '%/%'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE managed_resources m
        SET external_id = substr(m.external_id, length(e.environment) + 2)
        FROM executions e
        WHERE e.id = m.execution_id AND e.project_id = m.project_id
          AND m.resource_type = 'server_project'
          AND m.external_id LIKE e.environment || '/%'
        """
    )
