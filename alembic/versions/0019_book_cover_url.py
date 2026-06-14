"""Add cover_url to books for OpenLibrary cover thumbnails.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("books") as batch_op:
        batch_op.add_column(sa.Column("cover_url", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("books") as batch_op:
        batch_op.drop_column("cover_url")
