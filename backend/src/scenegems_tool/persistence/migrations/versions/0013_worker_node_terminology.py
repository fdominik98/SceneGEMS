"""Worker node terminology: the node tables, columns and stored keys take the name worker node.

SceneGEMS calls what was the master a control node and what was a node a worker node. The tables
node, node_capability, node_component and node_fingerprint become worker_node, worker_node_capability,
worker_node_component and worker_node_fingerprint; their node_id columns, job_event.node_id and
run_record.node_id become worker_node_id, and job.allowed_nodes becomes allowed_worker_nodes. The
constraints and the index are renamed with them, so every name still follows the naming convention
(schema/base.py).

Stored documents follow the wire names: resources.nodes of a campaign config (campaign_config_version,
campaign_preset) becomes resources.worker_nodes, and allowed_nodes of a kept job submission
(pipeline_job.submission) becomes allowed_worker_nodes. Nothing is deleted, and the downgrade renames
everything back.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-10
"""

from typing import Sequence, Tuple, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (old name, new name)
TABLES: Tuple[Tuple[str, str], ...] = (
    ("node", "worker_node"),
    ("node_capability", "worker_node_capability"),
    ("node_component", "worker_node_component"),
    ("node_fingerprint", "worker_node_fingerprint"),
)
# (table as of this revision, old column, new column)
COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("worker_node_capability", "node_id", "worker_node_id"),
    ("worker_node_component", "node_id", "worker_node_id"),
    ("worker_node_fingerprint", "node_id", "worker_node_id"),
    ("job", "allowed_nodes", "allowed_worker_nodes"),
    ("job_event", "node_id", "worker_node_id"),
    ("run_record", "node_id", "worker_node_id"),
)
# (table as of this revision, old constraint, new constraint) of the keys; renaming a primary key renames its index
CONSTRAINTS: Tuple[Tuple[str, str, str], ...] = (
    ("worker_node", "pk_node", "pk_worker_node"),
    ("worker_node_capability", "pk_node_capability", "pk_worker_node_capability"),
    ("worker_node_capability", "fk_node_capability_node_id_node", "fk_worker_node_capability_worker_node_id_worker_node"),
    ("worker_node_component", "pk_node_component", "pk_worker_node_component"),
    ("worker_node_component", "fk_node_component_node_id_node", "fk_worker_node_component_worker_node_id_worker_node"),
    ("worker_node_fingerprint", "pk_node_fingerprint", "pk_worker_node_fingerprint"),
    ("worker_node_fingerprint", "fk_node_fingerprint_node_id_node", "fk_worker_node_fingerprint_worker_node_id_worker_node"),
    ("job", "fk_job_lease_owner_node", "fk_job_lease_owner_worker_node"),
)
# (old table, table as of this revision, name the revisions give the CHECK constraint). The database holds every CHECK
# constraint as ck_<table>_<given name>, because the naming convention is applied to the already prefixed name; later
# revisions drop and create them by the given name (0012: _replace_check), so the stored names keep that shape.
CHECKS: Tuple[Tuple[str, str, str], ...] = (
    ("node", "worker_node", "status"),
    ("node_capability", "worker_node_capability", "job_type"),
    ("node_capability", "worker_node_capability", "slots_positive"),
    ("node_capability", "worker_node_capability", "slots_in_use_not_negative"),
)
INDEXES: Tuple[Tuple[str, str], ...] = (("ix_node_last_seen_at", "ix_worker_node_last_seen_at"),)
# Tables whose config column holds a campaign config
CONFIG_TABLES: Tuple[str, ...] = ("campaign_config_version", "campaign_preset")


def _stored_check_name(table: str, name: str) -> str:
    return f"ck_{table}_ck_{table}_{name}"


def _rename_config_key(old: str, new: str) -> None:
    """Rename a key of the resources section of every stored campaign config."""
    for table in CONFIG_TABLES:
        op.execute(
            f"UPDATE {table} SET config = jsonb_set(config #- '{{resources,{old}}}', '{{resources,{new}}}', config #> '{{resources,{old}}}')" f" WHERE config #> '{{resources,{old}}}' IS NOT NULL"
        )


def _rename_submission_key(old: str, new: str) -> None:
    """Rename a field of the job submissions the pipeline keeps until their job is linked."""
    op.execute(
        f"UPDATE pipeline_job SET submission = (submission - '{old}') || jsonb_build_object('{new}', submission -> '{old}')" f" WHERE submission IS NOT NULL AND jsonb_exists(submission, '{old}')"
    )


def upgrade() -> None:
    for old, new in TABLES:
        op.rename_table(old, new)
    for table, old, new in COLUMNS:
        op.alter_column(table, old, new_column_name=new)
    for table, old, new in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")
    for old_table, table, name in CHECKS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {_stored_check_name(old_table, name)} TO {_stored_check_name(table, name)}")
    for old, new in INDEXES:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
    _rename_config_key("nodes", "worker_nodes")
    _rename_submission_key("allowed_nodes", "allowed_worker_nodes")


def downgrade() -> None:
    _rename_submission_key("allowed_worker_nodes", "allowed_nodes")
    _rename_config_key("worker_nodes", "nodes")
    for old, new in INDEXES:
        op.execute(f"ALTER INDEX {new} RENAME TO {old}")
    for old_table, table, name in CHECKS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {_stored_check_name(table, name)} TO {_stored_check_name(old_table, name)}")
    for table, old, new in CONSTRAINTS:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {new} TO {old}")
    for table, old, new in COLUMNS:
        op.alter_column(table, new, new_column_name=old)
    for old, new in reversed(TABLES):
        op.rename_table(new, old)
