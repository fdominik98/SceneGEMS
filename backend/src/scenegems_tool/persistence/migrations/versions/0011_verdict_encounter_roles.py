"""Vessel roles per encounter on the verdict.

verdict.encounter_roles holds, per relation (keyed like rule_outcomes, for example "OS_0 - TS_1")
and situation type (a COLREGSType name other than OTHER), the vessel names by role ("give_way",
"stand_on") when the type first appeared. The relation key orders the vessels by id, so
verdict.encounters cannot say who gives way. It is NULL for the verdicts stored before this
revision, for unmonitored ones and when no pair met in an encounter.

The downgrade drops the column.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("verdict", sa.Column("encounter_roles", postgresql.JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("verdict", "encounter_roles")
