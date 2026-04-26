"""Add deadline reminder-sent tracking fields.

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(
            sa.Column("submit_reminder_sent", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("ranking_reminder_sent", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("bracket_reminder_round", sa.Integer(), nullable=True)
        )

    with op.batch_alter_table("meetups") as batch_op:
        batch_op.add_column(
            sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("submit_reminder_sent")
        batch_op.drop_column("ranking_reminder_sent")
        batch_op.drop_column("bracket_reminder_round")

    with op.batch_alter_table("meetups") as batch_op:
        batch_op.drop_column("reminder_sent")
