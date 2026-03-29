"""Add promoted column to books, drop one-per-member constraint.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade():
    with op.batch_alter_table("books") as batch_op:
        batch_op.add_column(sa.Column("promoted", sa.Boolean(), server_default="0", nullable=False))
        batch_op.drop_constraint("uq_one_book_per_member_per_season", type_="unique")


def downgrade():
    with op.batch_alter_table("books") as batch_op:
        batch_op.drop_column("promoted")
        batch_op.create_unique_constraint(
            "uq_one_book_per_member_per_season", ["submitter_id", "season_id"]
        )
