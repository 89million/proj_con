"""Add discussion_posts table.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discussion_posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("discussion_posts.id"), nullable=True),
        sa.Column("anchor_page", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # The thread list is always read season-scoped and ordered by anchor page.
    op.create_index(
        "ix_discussion_posts_season_anchor",
        "discussion_posts",
        ["season_id", "anchor_page"],
    )


def downgrade() -> None:
    op.drop_index("ix_discussion_posts_season_anchor", table_name="discussion_posts")
    op.drop_table("discussion_posts")
