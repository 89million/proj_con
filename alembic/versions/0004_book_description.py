"""Add optional description field to books table.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "description")
