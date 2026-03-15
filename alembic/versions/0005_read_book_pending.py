"""Add pending column to read_books.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade():
    op.add_column(
        "read_books",
        sa.Column("pending", sa.Boolean(), server_default="0", nullable=False),
    )


def downgrade():
    op.drop_column("read_books", "pending")
