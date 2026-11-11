"""Worker node instance number: every worker node gets a number of its own in the cluster.

MQTT topics name the subsystem that publishes and not the worker node it runs on, so the pooled
services of two worker nodes need names that differ: scene-generation-subsystem-1 and -2. The number
is the worker node's instance_number. The control node gives a new worker node the lowest free one at
its first Hello and tells it in its Welcome, and the worker node keeps it while its row exists.

The worker nodes already stored are numbered in the order they registered. The downgrade drops the
column; a worker node of the older release names its services by its own id again.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-11
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, Sequence[str], None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("worker_node", sa.Column("instance_number", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE worker_node SET instance_number = numbered.number"
        " FROM (SELECT id, row_number() OVER (ORDER BY registered_at, id) AS number FROM worker_node) AS numbered"
        " WHERE worker_node.id = numbered.id"
    )
    op.alter_column("worker_node", "instance_number", nullable=False)
    op.create_unique_constraint(op.f("uq_worker_node_instance_number"), "worker_node", ["instance_number"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_worker_node_instance_number"), "worker_node", type_="unique")
    op.drop_column("worker_node", "instance_number")
