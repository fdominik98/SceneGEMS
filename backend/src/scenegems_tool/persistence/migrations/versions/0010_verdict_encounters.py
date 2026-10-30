"""Encounter types per vessel pair on the verdict.

verdict.encounters holds, per relation (keyed like rule_outcomes, for example "OS_0 - TS_1"),
the situation types (COLREGSType names) the monitor saw for the pair, in order of first
appearance. It is NULL for the verdicts stored before this revision and for unmonitored ones.

The downgrade drops the column.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("verdict", sa.Column("encounters", postgresql.JSONB(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("verdict", "encounters")
