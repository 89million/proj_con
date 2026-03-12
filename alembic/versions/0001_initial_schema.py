"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-11

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("google_id", sa.String(), nullable=False, unique=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "state",
            sa.Enum("submit", "ranking", "bracket", "complete", name="seasonstate"),
            nullable=False,
            server_default="submit",
        ),
        sa.Column("page_limit", sa.Integer(), nullable=False, server_default="400"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "read_books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("won", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("added_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("submitter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("submitter_id", "season_id", name="uq_one_book_per_member_per_season"),
        sa.UniqueConstraint("title", "author", "season_id", name="uq_no_duplicate_titles_per_season"),
    )

    op.create_table(
        "borda_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "season_id", "book_id", name="uq_one_rank_per_book_per_voter"),
    )

    op.create_table(
        "seeds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.UniqueConstraint("season_id", "book_id", name="uq_one_seed_per_book"),
        sa.UniqueConstraint("season_id", "seed", name="uq_one_book_per_seed"),
    )

    op.create_table(
        "bracket_matchups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id"), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("book_a_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("book_b_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("winner_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=True),
    )

    op.create_table(
        "bracket_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("matchup_id", sa.Integer(), sa.ForeignKey("bracket_matchups.id"), nullable=False),
        sa.Column("book_id", sa.Integer(), sa.ForeignKey("books.id"), nullable=False),
        sa.Column("voted_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.UniqueConstraint("user_id", "matchup_id", name="uq_one_vote_per_matchup_per_user"),
    )


def downgrade() -> None:
    op.drop_table("bracket_votes")
    op.drop_table("bracket_matchups")
    op.drop_table("seeds")
    op.drop_table("borda_votes")
    op.drop_table("books")
    op.drop_table("read_books")
    op.drop_table("seasons")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS seasonstate")
