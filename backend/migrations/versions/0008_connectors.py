"""Table `connectors` : statut des sondes et références des jetons (#260).

Zone sensible, à relire. Faire un `pg_dump` avant le déploiement. Additive.

- Upgrade : crée `connectors` (un connecteur par ligne ; droits déclarés, droits vérifiés par la
  dernière sonde, statut, références vers `secrets`). Aucun jeton : seulement des identifiants.
- Downgrade : supprime `connectors` ; le statut `incomplete` est perdu (sonde à relancer).
- Verrous : CREATE TABLE seul, aucune table existante touchée.
- Versions mixtes : l'ancien code ignore la table ; aucun changement de comportement.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Écart voulu avec la spec : pas de CHECK sur `provider` (anthropic, dns, ... s'ajoutent par
    # le catalogue, pas par migration) ; `provider` est unique, c'est la clé du connecteur.
    op.execute(
        """
        CREATE TABLE connectors (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            provider text NOT NULL UNIQUE,
            name text NOT NULL,
            status text NOT NULL DEFAULT 'incomplete'
                CHECK (status IN ('ok', 'incomplete', 'revoked')),
            declared_scopes jsonb NOT NULL,
            verified_scopes jsonb NOT NULL DEFAULT '{}',
            read_secret_ref text,
            write_secret_ref text,
            last_probe_at timestamptz
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE connectors")
