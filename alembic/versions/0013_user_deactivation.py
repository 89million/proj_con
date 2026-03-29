"""Add is_active column to users for soft account deletion.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1")
        )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_active")
