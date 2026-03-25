"""Add display_name and email_notifications to users.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade():
    op.add_column("users", sa.Column("display_name", sa.String(), nullable=True))
    op.add_column(
        "users",
        sa.Column("email_notifications", sa.Boolean(), server_default="1", nullable=False),
    )


def downgrade():
    op.drop_column("users", "email_notifications")
    op.drop_column("users", "display_name")
