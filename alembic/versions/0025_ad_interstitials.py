"""Add THE MONK ad interstitials: ad_impressions, users.ads_opted_out, app_settings.

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"


def upgrade():
    op.add_column(
        "users",
        sa.Column("ads_opted_out", sa.Boolean(), server_default="0", nullable=False),
    )

    op.create_table(
        "ad_impressions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("ad_slug", sa.String(), nullable=False),
        sa.Column("shown_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ads_enabled", sa.Boolean(), server_default="1", nullable=False),
    )
    op.execute("INSERT INTO app_settings (id, ads_enabled) VALUES (1, true)")


def downgrade():
    op.drop_table("app_settings")
    op.drop_table("ad_impressions")
    op.drop_column("users", "ads_opted_out")
