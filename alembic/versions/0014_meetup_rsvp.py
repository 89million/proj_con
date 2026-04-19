"""Add meetup_rsvps table.

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meetup_rsvps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("meetup_id", sa.Integer(), sa.ForeignKey("meetups.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("venue", sa.String(), nullable=True),
        sa.Column("discord_ok", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meetup_id", "user_id", name="uq_one_rsvp_per_meetup_user"),
    )


def downgrade() -> None:
    op.drop_table("meetup_rsvps")
