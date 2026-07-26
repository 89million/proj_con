"""Link discussion posts to quotes on the book's wall.

A discussion post can open from a passage. The quote itself belongs to the
book (book_quotes), so it survives the season; the post keeps a pointer so the
two surfaces can cross-link.

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("discussion_posts", sa.Column("quote_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_discussion_posts_quote_id",
        "discussion_posts",
        "book_quotes",
        ["quote_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_discussion_posts_quote_id", "discussion_posts", type_="foreignkey")
    op.drop_column("discussion_posts", "quote_id")
