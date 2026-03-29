"""Add nudge timestamp and deadline columns to seasons.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade():
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(sa.Column("last_nudge_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("submit_deadline", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("ranking_deadline", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("bracket_round_hours", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("bracket_round_hours")
        batch_op.drop_column("ranking_deadline")
        batch_op.drop_column("submit_deadline")
        batch_op.drop_column("last_nudge_at")
