"""Design space exploration: a job type, a pipeline stage and a workbench origin of their own.

The first step of the chain runs as the job type design_space_exploration at the stage
explore_design_space, and a workbench entry of its page has the origin design_space_exploration,
so the CHECK constraints of job.job_type, node_capability.job_type, scenario_case.stage,
pipeline_job.stage and campaign.origin take the new values. A campaign that explores has one class
for the exploration itself (id exploration), which stands for no scenario: campaign_class allows a
vessel count of 0.

The downgrade deletes what an older release cannot read: the campaigns that explored (with their
classes, cases and pipeline jobs), the design space exploration jobs and the nodes' capability rows
of the type, which a node of the newer release lists again in its Hello.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum values as of this revision; a later revision that adds a value replaces the constraint.
PREVIOUS_JOB_TYPES = ("scene_generation", "trajectory_generation", "simulation", "monitoring.post_hoc", "calibration.deviation")
JOB_TYPES = ("design_space_exploration",) + PREVIOUS_JOB_TYPES
PREVIOUS_PIPELINE_STAGES = ("generate_scene", "monitor_scene", "generate_trajectories", "monitor_trajectories", "simulate", "monitor", "calibrate", "verdict")
PIPELINE_STAGES = ("explore_design_space",) + PREVIOUS_PIPELINE_STAGES
PREVIOUS_CAMPAIGN_ORIGINS = ("wizard", "cli", "scene_generation", "trajectory_generation", "simulation", "live_session")
CAMPAIGN_ORIGINS = ("wizard", "cli", "design_space_exploration", "scene_generation", "trajectory_generation", "simulation", "live_session")

JOB_TYPE = "design_space_exploration"
STAGE = "explore_design_space"
ORIGIN = "design_space_exploration"
EXPLORATION_CLASS = "exploration"  # the class of the exploration itself (assurance/campaign/campaign_inputs.py)
PREVIOUS_CLASS_COUNTS = "vessel_count >= 1 AND obstacle_count >= 0"
CLASS_COUNTS = "vessel_count >= 0 AND obstacle_count >= 0"


def _one_of(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(name, table, type_="check")
    op.create_check_constraint(name, table, condition)


def _set_constraints(job_types: Sequence[str], stages: Sequence[str], origins: Sequence[str], class_counts: str) -> None:
    for table in ("job", "node_capability"):
        _replace_check(table, f"ck_{table}_job_type", _one_of("job_type", job_types))
    for table in ("scenario_case", "pipeline_job"):
        _replace_check(table, f"ck_{table}_stage", _one_of("stage", stages))
    _replace_check("campaign", "ck_campaign_origin", _one_of("origin", origins))
    _replace_check("campaign_class", "ck_campaign_class_counts_of_the_scenario", class_counts)


def upgrade() -> None:
    _set_constraints(JOB_TYPES, PIPELINE_STAGES, CAMPAIGN_ORIGINS, CLASS_COUNTS)


def downgrade() -> None:
    op.execute(f"DELETE FROM campaign WHERE origin = '{ORIGIN}' OR id IN (SELECT campaign_id FROM campaign_class WHERE class_id = '{EXPLORATION_CLASS}')")
    op.execute(f"DELETE FROM pipeline_job WHERE stage = '{STAGE}'")
    op.execute(f"DELETE FROM job WHERE job_type = '{JOB_TYPE}'")
    op.execute(f"DELETE FROM node_capability WHERE job_type = '{JOB_TYPE}'")
    _set_constraints(PREVIOUS_JOB_TYPES, PREVIOUS_PIPELINE_STAGES, PREVIOUS_CAMPAIGN_ORIGINS, PREVIOUS_CLASS_COUNTS)
