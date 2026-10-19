"""Raison d'invalidation d'un plan : `plans.invalidation` (S12, D5).

Zone sensible, à relire. Faire un `pg_dump` avant le déploiement.

- Upgrade : ajoute `plans.invalidation jsonb NULL` (`{reason, changes}`), remplit les plans déjà
  `invalidated` (seul `reject_admin` les écrivait) avec `{reason: admin_rejected, changes: []}`,
  puis pose le CHECK `(status = 'invalidated') = (invalidation IS NOT NULL)`. Le remplissage précède
  le CHECK : aucune ligne existante ne peut le violer. `expired` n'est pas `invalidated` : sa
  colonne reste NULL (sa raison n'existe que dans la carte). Le déclencheur d'immuabilité des plans
  ne couvre pas cette colonne.
- Downgrade : retire le CHECK puis la colonne. La raison est perdue, les statuts sont conservés
  (`invalidated` et `expired` restent permis par le CHECK `plans_status` d'avant).
- Verrous : ACCESS EXCLUSIVE bref sur `plans` (colonne nullable sans défaut : pas de réécriture ;
  le CHECK valide les lignes existantes en un seul passage). Table de quelques lignes.
- Versions mixtes : l'ancien code ignore la colonne, mais son `reject_admin` écrirait `invalidated`
  sans raison et le CHECK refuserait : déployer le code et la migration ensemble.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN invalidation jsonb")
    op.execute(
        """
        UPDATE plans
        SET invalidation = '{"reason": "admin_rejected", "changes": []}'::jsonb
        WHERE status = 'invalidated'
        """
    )
    op.execute(
        """
        ALTER TABLE plans ADD CONSTRAINT plans_invalidation
        CHECK ((status = 'invalidated') = (invalidation IS NOT NULL))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE plans DROP CONSTRAINT plans_invalidation")
    op.execute("ALTER TABLE plans DROP COLUMN invalidation")
