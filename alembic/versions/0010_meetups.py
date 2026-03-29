"""Add meetup scheduling tables (meetups, meetup_options, meetup_votes).

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade():
    # Create meetups first without the finalized_option_id FK (circular ref)
    op.create_table(
        "meetups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), unique=True, nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "meetup_options",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("meetup_id", sa.Integer(), sa.ForeignKey("meetups.id"), nullable=False),
        sa.Column("proposed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_datetime", sa.DateTime(), nullable=False),
        sa.Column("location", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "meetup_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("option_id", sa.Integer(), sa.ForeignKey("meetup_options.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("option_id", "user_id", name="uq_one_vote_per_user_per_option"),
    )

    # Add finalized_option_id (no FK to avoid circular dependency)
    op.add_column(
        "meetups",
        sa.Column("finalized_option_id", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("meetups", "finalized_option_id")
    op.drop_table("meetup_votes")
    op.drop_table("meetup_options")
    op.drop_table("meetups")
