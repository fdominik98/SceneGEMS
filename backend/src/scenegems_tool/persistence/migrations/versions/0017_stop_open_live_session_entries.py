"""Stop the live session entries that are still open without a run.

The control node no longer runs live sessions of the workbench: a simulation is a job on a worker
node. Until now the gateway opened a workbench entry of origin live_session for each session and
recorded the session's run as its one case; an entry whose session ended without a run was stopped
when the control node started again. Nothing does that any more, so such an entry would want to run
for ever. This revision asks every one of them to stop, as the operator's Stop does: an entry of
origin live_session that is not finished, not asked to stop already and has no case. The pipeline
engine then moves it to stopped on its next tick.

Entries with a recorded run are left alone: the engine finishes them as before, and they stay in
the history (origin live_session, run records of source live_session).

The downgrade changes nothing: a stopped entry stays stopped.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0017"
down_revision: Union[str, Sequence[str], None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE campaign SET desired_state = 'stopped', updated_at = now()"
        " WHERE origin = 'live_session' AND desired_state <> 'stopped' AND actual_state NOT IN ('stopped', 'completed')"
        " AND NOT EXISTS (SELECT 1 FROM scenario_case WHERE scenario_case.campaign_id = campaign.id)"
    )


def downgrade() -> None:
    pass
