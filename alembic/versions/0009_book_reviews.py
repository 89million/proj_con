"""Add book_reviews table for star ratings and text reviews.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade():
    op.create_table(
        "book_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("read_book_id", sa.Integer(), sa.ForeignKey("read_books.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("read_book_id", "user_id", name="uq_one_review_per_user_per_book"),
    )


def downgrade():
    op.drop_table("book_reviews")
