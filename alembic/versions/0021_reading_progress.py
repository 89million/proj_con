"""Add reading_progress table.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reading_progress",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("percent", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("season_id", "user_id", name="uq_one_progress_per_season_user"),
    )


def downgrade() -> None:
    op.drop_table("reading_progress")
