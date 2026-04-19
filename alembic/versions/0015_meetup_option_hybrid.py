"""Add is_hybrid to meetup_options.

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("meetup_options") as batch_op:
        batch_op.add_column(
            sa.Column("is_hybrid", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("meetup_options") as batch_op:
        batch_op.drop_column("is_hybrid")
