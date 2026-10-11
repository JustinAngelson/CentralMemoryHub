"""Phase 0 extensions only. No CMH application tables."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    for name in ("vector", "ltree", "pgcrypto"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {name}")


def downgrade():
    # No CASCADE: refuse to remove extensions used by any later schema.
    for name in ("vector", "ltree", "pgcrypto"):
        op.execute(f"DROP EXTENSION IF EXISTS {name}")
