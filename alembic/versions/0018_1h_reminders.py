"""Add 1-hour reminder tracking fields to seasons and meetups.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(
            sa.Column(
                "submit_1h_reminder_sent",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "ranking_1h_reminder_sent",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column("bracket_1h_reminder_round", sa.Integer(), nullable=True)
        )

    with op.batch_alter_table("meetups") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reminder_1h_sent",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("submit_1h_reminder_sent")
        batch_op.drop_column("ranking_1h_reminder_sent")
        batch_op.drop_column("bracket_1h_reminder_round")

    with op.batch_alter_table("meetups") as batch_op:
        batch_op.drop_column("reminder_1h_sent")
