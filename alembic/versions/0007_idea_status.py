"""Add status and admin_note columns to feature_ideas.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade():
    op.add_column(
        "feature_ideas",
        sa.Column(
            "status",
            sa.Enum("proposed", "in_progress", "done", "wont_do", name="ideastatus"),
            server_default="proposed",
            nullable=False,
        ),
    )
    op.add_column(
        "feature_ideas",
        sa.Column("admin_note", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("feature_ideas", "admin_note")
    op.drop_column("feature_ideas", "status")
    op.execute("DROP TYPE IF EXISTS ideastatus")
