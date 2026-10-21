"""Magasin de secrets chiffrés (#256).

Zone sensible, à relire. Faire un `pg_dump` avant le déploiement. Additive.

- Upgrade : crée `secrets` (id, kind, key_id, nonce, ciphertext, created_by, created_at,
  rotated_at).
  Seul le texte chiffré (AES-256-GCM) y entre ; la clé maître vit dans un volume dédié, pas en base.
- Downgrade : supprime `secrets` ; les secrets saisis sont perdus (à ressaisir).
- Verrous : CREATE TABLE seul, aucune table existante touchée.
- Versions mixtes : l'ancien code ignore la table ; aucun changement de comportement.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE secrets (
            id text PRIMARY KEY,
            kind text NOT NULL,
            key_id text NOT NULL,
            nonce bytea NOT NULL,
            ciphertext bytea NOT NULL,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            rotated_at timestamptz
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE secrets")
