"""Add ranking_days to seasons for dynamic ranking deadline computation.

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(sa.Column("ranking_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("ranking_days")
