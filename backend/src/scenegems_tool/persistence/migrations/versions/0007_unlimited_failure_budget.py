"""Unlimited failure budgets: campaign_class.failure_budget may be NULL.

A NULL failure budget is unlimited: the class is never abandoned and replaces its dropped and
failed cases until its quota is complete. Existing classes keep their numbers. The check
that a budget is not negative stays (NULL passes it).

The downgrade makes the column NOT NULL again. It fails while a class with an unlimited
budget exists, which is the safe outcome.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("campaign_class", "failure_budget", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("campaign_class", "failure_budget", existing_type=sa.Integer(), nullable=False)
