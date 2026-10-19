"""Comptes, sessions, invitations et équipes personnelles (auth, #221).

Zone sensible, à relire. Faire un `pg_dump` avant le déploiement. Additive.

- Upgrade : `users` gagne `password_hash`, `disabled_at`, `invited_by` (FK) et un index unique sur
  `lower(email)` ; `teams` gagne `personal` (défaut false : les équipes existantes restent
  non personnelles) ; crée `sessions` et `invitations` (seuls des condensats, jamais de jeton).
- Downgrade : retire tout cela ; sessions, invitations et mots de passe sont perdus.
- Verrous : ALTER brefs (colonnes nullables ou à défaut constant, sans réécriture lourde) ; l'index
  unique parcourt `users` (quelques lignes). Il échoue si deux e-mails existants ne diffèrent que
  par la casse : à corriger avant déploiement.
- Versions mixtes : l'ancien code ignore ces colonnes et tables ; aucun changement de comportement.

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN password_hash text")
    op.execute("ALTER TABLE users ADD COLUMN disabled_at timestamptz")
    op.execute("ALTER TABLE users ADD COLUMN invited_by uuid REFERENCES users(id)")
    op.execute("CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))")
    op.execute("ALTER TABLE teams ADD COLUMN personal boolean NOT NULL DEFAULT false")
    op.execute(
        """
        CREATE TABLE sessions (
            id_hash text PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id),
            csrf_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_sessions_user_id ON sessions (user_id)")
    op.execute(
        """
        CREATE TABLE invitations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            token_hash text NOT NULL UNIQUE,
            email text NOT NULL,
            team_id uuid REFERENCES teams(id),
            role text NOT NULL,
            invited_by uuid NOT NULL REFERENCES users(id),
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            CONSTRAINT invitations_role
                CHECK (role IN ('developer', 'team_admin', 'org_admin'))
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE invitations")
    op.execute("DROP TABLE sessions")
    op.execute("ALTER TABLE teams DROP COLUMN personal")
    op.execute("DROP INDEX uq_users_email_lower")
    op.execute("ALTER TABLE users DROP COLUMN invited_by")
    op.execute("ALTER TABLE users DROP COLUMN disabled_at")
    op.execute("ALTER TABLE users DROP COLUMN password_hash")
