"""Add cover_url to read_books for cover thumbnails on the 'books we've read' page.

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("read_books") as batch_op:
        batch_op.add_column(sa.Column("cover_url", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("read_books") as batch_op:
        batch_op.drop_column("cover_url")
