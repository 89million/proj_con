"""make google_id nullable for pre-registered users

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-14

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("users", "google_id", nullable=True)


def downgrade() -> None:
    op.alter_column("users", "google_id", nullable=False)
