"""Add book_quotes, plus page_count and season_id on read_books.

read_books was a flat copy of the winning book — no page count and no link back
to where it came from. Both are needed to page-anchor quotes and to tell whether
a reader has finished the book they're reading.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("read_books", sa.Column("page_count", sa.Integer(), nullable=True))
    op.add_column("read_books", sa.Column("season_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_read_books_season_id", "read_books", "seasons", ["season_id"], ["id"]
    )

    # Best-effort backfill for books already in the table. Exact title+author
    # match against `books`; anything that doesn't match stays null, which the
    # app treats as "can't page-anchor this one" rather than as an error.
    op.execute(
        """
        UPDATE read_books SET page_count = (
            SELECT b.page_count FROM books b
            WHERE lower(b.title) = lower(read_books.title)
              AND lower(b.author) = lower(read_books.author)
            LIMIT 1
        )
        WHERE page_count IS NULL
        """
    )
    # Only won books can be traced to a season — a book that won its bracket is
    # the winner_id of its season's last matchup.
    op.execute(
        """
        UPDATE read_books SET season_id = (
            SELECT b.season_id FROM books b
            JOIN bracket_matchups m ON m.winner_id = b.id
            WHERE lower(b.title) = lower(read_books.title)
              AND lower(b.author) = lower(read_books.author)
            ORDER BY m.round DESC
            LIMIT 1
        )
        WHERE season_id IS NULL AND won
        """
    )

    op.create_table(
        "book_quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("read_book_id", sa.Integer(), sa.ForeignKey("read_books.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_book_quotes_book_page", "book_quotes", ["read_book_id", "page"]
    )


def downgrade() -> None:
    op.drop_index("ix_book_quotes_book_page", table_name="book_quotes")
    op.drop_table("book_quotes")
    op.drop_constraint("fk_read_books_season_id", "read_books", type_="foreignkey")
    op.drop_column("read_books", "season_id")
    op.drop_column("read_books", "page_count")
