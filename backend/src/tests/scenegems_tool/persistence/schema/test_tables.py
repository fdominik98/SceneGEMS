import pytest

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import Base, JobEventRow, JobRow, NodeCapabilityRow, NodeRow


def _check_constraint(table, name):
    return next(constraint for constraint in table.constraints if constraint.name == name)


CLUSTER_TABLES = {"node", "node_capability", "node_component", "node_fingerprint", "job", "job_event"}
CAMPAIGN_TABLES = {
    "campaign",
    "campaign_config_version",
    "campaign_class",
    "scenario_case",
    "pipeline_job",
    "pipeline_cursor",
    "run_record",
    "verdict",
    "campaign_event",
    "artifact",
    "artifact_reference",
    "calibration_result",
}
SETTING_TABLES = {"cluster_domain", "campaign_preset"}


def test_tables():
    assert set(Base.metadata.tables) == CLUSTER_TABLES | CAMPAIGN_TABLES | SETTING_TABLES


def test_the_cluster_domain_has_one_row_at_most():
    from scenegems_tool.persistence.schema import ClusterDomainRow

    assert "ck_cluster_domain_single_row" in {constraint.name for constraint in ClusterDomainRow.__table__.constraints}


def test_jobs_have_an_availability_and_events_their_transaction():
    assert not JobRow.__table__.c.available_at.nullable
    tx_id = JobEventRow.__table__.c.tx_id
    assert not tx_id.nullable and "pg_current_xact_id()" in str(tx_id.server_default.arg)
    index = next(index for index in JobEventRow.__table__.indexes if index.name == "ix_job_event_tx_id_id")
    assert [column.name for column in index.columns] == ["tx_id", "id"]


@pytest.mark.parametrize(
    "table, column, values",
    [
        (JobRow.__table__, "job_type", [job_type.value for job_type in JobType]),
        (JobRow.__table__, "state", [state.value for state in JobState]),
        (NodeCapabilityRow.__table__, "job_type", [job_type.value for job_type in JobType]),
        (JobEventRow.__table__, "to_state", [state.value for state in JobState]),
    ],
)
def test_enum_columns_store_values(table, column, values):
    assert table.c[column].type.enums == values


def test_enum_constraints_follow_the_naming_convention():
    names = {constraint.name for constraint in JobRow.__table__.constraints}
    assert {"ck_job_job_type", "ck_job_state", "pk_job", "uq_job_idempotency_key", "uq_job_lease_id", "fk_job_lease_owner_node"} <= names
    assert "ck_node_status" in {constraint.name for constraint in NodeRow.__table__.constraints}


def test_a_job_requires_components_and_a_node_offers_them():
    column = JobRow.__table__.c.required_components
    assert not column.nullable and "'[]'::jsonb" in str(column.server_default.arg)
    assert [column.name for column in Base.metadata.tables["node_component"].primary_key.columns] == ["node_id", "component"]


def test_idempotency_key_is_unique_and_required():
    column = JobRow.__table__.c.idempotency_key
    assert column.unique and not column.nullable


def test_queue_index_covers_queued_jobs_in_claim_order():
    index = next(index for index in JobRow.__table__.indexes if index.name == "ix_job_queue_order")
    assert str(index.dialect_options["postgresql"]["where"]) == "state = 'queued'"
    assert [str(expression) for expression in index.expressions] == ["priority DESC", "job.submitted_at", "job.seq"]


def test_lease_columns_are_optional_and_owner_references_a_node():
    table = JobRow.__table__
    assert all(table.c[name].nullable for name in ("lease_id", "lease_owner", "lease_expires_at"))
    assert {foreign_key.target_fullname for foreign_key in table.c.lease_owner.foreign_keys} == {"node.id"}


def test_active_lease_must_be_complete():
    constraint = _check_constraint(JobRow.__table__, "ck_job_active_lease_complete")
    assert "lease_expires_at IS NOT NULL" in str(constraint.sqltext)


def test_node_children_are_deleted_with_the_node():
    for table_name in ("node_capability", "node_component", "node_fingerprint"):
        (foreign_key,) = Base.metadata.tables[table_name].c.node_id.foreign_keys
        assert foreign_key.ondelete == "CASCADE"
