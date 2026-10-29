"""The cluster's settings: its domain configuration and saved campaign presets.

New tables: cluster_domain (one row at most, id 1: the COLREGS constants, vessel types and
obstacle types of the cluster; without it the master's default domain files apply) and
campaign_preset (campaign configs saved under a unique name). Nothing existing changes, so
the downgrade drops both tables and the saved content with them.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cluster_domain",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("colregs_constants", sa.Text(), nullable=False),
        sa.Column("vessel_types", sa.Text(), nullable=False),
        sa.Column("obstacle_types", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_cluster_domain_single_row"),
        sa.PrimaryKeyConstraint("id", name="pk_cluster_domain"),
    )
    op.create_table(
        "campaign_preset",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_preset"),
        sa.UniqueConstraint("name", name="uq_campaign_preset_name"),
    )


def downgrade() -> None:
    op.drop_table("campaign_preset")
    op.drop_table("cluster_domain")
