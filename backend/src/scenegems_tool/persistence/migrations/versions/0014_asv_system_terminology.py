"""ASV system terminology: stored component ids and stack keys take the name asv_system.

SceneGEMS calls what was the ASV software of a vessel stack its ASV system. No table or column
carries the name, but stored values do: the components asv_software/replay and
asv_software/usv_navigation (worker_node_component.component, job.required_components and the
details of events) become asv_system/..., and the key asv_software of a vessel's stack
(job.payload, job.result, pipeline_job.submission, run_record.stack) becomes asv_system.

Campaign configs and calibration results are left alone: neither holds the name, and both are
stored next to a hash of their content. Nothing is deleted, and the downgrade renames everything back.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-10
"""

from typing import Sequence, Tuple, Union

from alembic import op

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "asv_software"
NEW_NAME = "asv_system"
# (table, JSONB column) that may hold the name as a key or at the start of a component id
JSON_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("job", "payload"),
    ("job", "required_components"),
    ("job", "result"),
    ("job_event", "detail"),
    ("pipeline_job", "submission"),
    ("run_record", "stack"),
    ("campaign_event", "detail"),
)


def _rename(old: str, new: str) -> None:
    op.execute(f"UPDATE worker_node_component SET component = '{new}/' || substr(component, {len(old) + 2}) WHERE starts_with(component, '{old}/')")
    for table, column in JSON_COLUMNS:
        # In the text of a JSONB value a key is "<name>" and a component id starts with "<name>/
        op.execute(
            f"UPDATE {table} SET {column} = replace(replace({column}::text, '\"{old}\"', '\"{new}\"'), '\"{old}/', '\"{new}/')::jsonb"
            f" WHERE {column} IS NOT NULL AND position('\"{old}' in {column}::text) > 0"
        )


def upgrade() -> None:
    _rename(OLD_NAME, NEW_NAME)


def downgrade() -> None:
    _rename(NEW_NAME, OLD_NAME)
