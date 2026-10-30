"""One simulation job type, and node components.

The three simulation job types become simulation: an existing job keeps its payload with runner
set from its old type (simulation.kinematic to kinematic; simulation.ardupilot_sim and
simulation.gazebo to ardupilot, whose payload already names its simulation_layer). A job gets
required_components (empty for existing jobs, which any node may then claim by its slots), and
the new node_component table holds the components each node offers. Node capability rows of the
old simulation types are deleted: a node lists its slots and components again in its Hello.

The downgrade maps simulation back by the runner and the simulation layer of the payload, drops
runner from the payload, drops node_component and required_components, and deletes the simulation
capability rows, which a node of the older release lists again.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREVIOUS_JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation.kinematic", "simulation.ardupilot_sim", "simulation.gazebo", "monitoring.post_hoc", "calibration.deviation")
JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation", "monitoring.post_hoc", "calibration.deviation")
# The runner each old simulation job type runs as
RUNNERS = {"simulation.kinematic": "kinematic", "simulation.ardupilot_sim": "ardupilot", "simulation.gazebo": "ardupilot"}


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _drop_job_type_constraints() -> None:
    for table in ("job", "node_capability"):
        op.drop_constraint(f"ck_{table}_job_type", table, type_="check")


def _create_job_type_constraints(job_types: Sequence[str]) -> None:
    for table in ("job", "node_capability"):
        op.create_check_constraint(f"ck_{table}_job_type", table, _one_of("job_type", job_types))


def upgrade() -> None:
    _drop_job_type_constraints()
    op.execute(f"DELETE FROM node_capability WHERE {_one_of('job_type', RUNNERS)}")
    for job_type, runner in RUNNERS.items():
        op.execute(f"UPDATE job SET job_type = 'simulation', payload = jsonb_set(payload, '{{runner}}', '\"{runner}\"') WHERE job_type = '{job_type}'")
    _create_job_type_constraints(JOB_TYPES)
    op.add_column("job", sa.Column("required_components", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.create_table(
        "node_component",
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "component", name="pk_node_component"),
        sa.ForeignKeyConstraint(["node_id"], ["node.id"], name="fk_node_component_node_id_node", ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("node_component")
    op.drop_column("job", "required_components")
    _drop_job_type_constraints()
    op.execute("DELETE FROM node_capability WHERE job_type = 'simulation'")
    op.execute("UPDATE job SET job_type = 'simulation.gazebo' WHERE job_type = 'simulation' AND payload ->> 'runner' = 'ardupilot' AND payload ->> 'simulation_layer' = 'gazebo'")
    op.execute("UPDATE job SET job_type = 'simulation.ardupilot_sim' WHERE job_type = 'simulation' AND payload ->> 'runner' = 'ardupilot'")
    op.execute("UPDATE job SET job_type = 'simulation.kinematic' WHERE job_type = 'simulation'")
    op.execute(f"UPDATE job SET payload = payload - 'runner' WHERE {_one_of('job_type', RUNNERS)}")
    _create_job_type_constraints(PREVIOUS_JOB_TYPES)
