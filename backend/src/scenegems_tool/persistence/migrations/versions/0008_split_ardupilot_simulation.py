"""Split simulation.ardupilot into simulation.ardupilot_sim and simulation.gazebo.

A node offers SITL's own physics and Gazebo as separate job types now, so a Gazebo node needs
the Gazebo image and a SITL node does not. Existing jobs take the type of their payload's
simulation layer. Node capabilities of the old type are deleted: a node lists its capabilities
again in its Hello.

The downgrade maps both types back to simulation.ardupilot and deletes the node capabilities of
the new types, which a node of the older release lists again.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PREVIOUS_JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation.kinematic", "simulation.ardupilot", "monitoring.post_hoc", "calibration.deviation")
JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation.kinematic", "simulation.ardupilot_sim", "simulation.gazebo", "monitoring.post_hoc", "calibration.deviation")


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
    op.execute("DELETE FROM node_capability WHERE job_type = 'simulation.ardupilot'")
    op.execute("UPDATE job SET job_type = 'simulation.gazebo' WHERE job_type = 'simulation.ardupilot' AND payload ->> 'simulation_layer' = 'gazebo'")
    op.execute("UPDATE job SET job_type = 'simulation.ardupilot_sim' WHERE job_type = 'simulation.ardupilot'")
    _create_job_type_constraints(JOB_TYPES)


def downgrade() -> None:
    _drop_job_type_constraints()
    op.execute("DELETE FROM node_capability WHERE job_type IN ('simulation.ardupilot_sim', 'simulation.gazebo')")
    op.execute("UPDATE job SET job_type = 'simulation.ardupilot' WHERE job_type IN ('simulation.ardupilot_sim', 'simulation.gazebo')")
    _create_job_type_constraints(PREVIOUS_JOB_TYPES)
