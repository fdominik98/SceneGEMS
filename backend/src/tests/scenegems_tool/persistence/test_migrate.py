import importlib
from datetime import datetime, timezone

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.database import DATABASE_URL_ENV, DatabaseNotConfigured
from scenegems_tool.persistence.migrate import MIGRATIONS_FOLDER, alembic_config, main, upgrade_database
from scenegems_tool.persistence.schema import (
    ArtifactHolderKind,
    Base,
    CampaignActualState,
    CampaignClassState,
    CampaignDesiredState,
    CampaignEventKind,
    CampaignKind,
    CampaignOrigin,
    CaseState,
    JobEventKind,
    MonitorImplementation,
    NodeStatus,
    PipelineStage,
    RunSource,
    StepKind,
    TrajectoryGeneratorImplementation,
    VerdictState,
)
from scenegems_tool.persistence.schema.campaign_tables import KIND_OF_ORIGIN_CHECK
from tests.scenegems_tool.persistence.schema.test_tables import CAMPAIGN_TABLES, CLUSTER_TABLES, SETTING_TABLES

ALL_TABLES = CLUSTER_TABLES | CAMPAIGN_TABLES | SETTING_TABLES


def _scripts() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config("postgresql://u:p@db/scenegems"))


def _revision(module: str):
    return importlib.import_module(f"scenegems_tool.persistence.migrations.versions.{module}")


def _values(enum_class) -> set:
    return {member.value for member in enum_class}


def test_migrations_live_in_the_package():
    assert (MIGRATIONS_FOLDER / "env.py").is_file()
    assert _scripts().dir == str(MIGRATIONS_FOLDER)


def test_revisions_form_one_line():
    scripts = _scripts()
    assert scripts.get_heads() == ["0012"]
    revisions = list(scripts.walk_revisions())
    assert [revision.revision for revision in revisions] == ["0012", "0011", "0010", "0009", "0008", "0007", "0006", "0005", "0004", "0003", "0002", "0001"]
    assert [revision.down_revision for revision in revisions] == ["0011", "0010", "0009", "0008", "0007", "0006", "0005", "0004", "0003", "0002", "0001", None]
    assert all(len(revision.revision) == 4 and revision.revision.isdigit() for revision in revisions)


def test_url_with_percent_encoding_reaches_alembic_unchanged():
    assert alembic_config("postgresql://u:p%40ss@db/scenegems").get_main_option("sqlalchemy.url") == "postgresql+psycopg://u:p%40ss@db/scenegems"


def test_config_needs_a_url(monkeypatch):
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(DatabaseNotConfigured):
        alembic_config()


def test_revision_enum_values_match_the_code():
    # The revisions spell the CHECK constraint values out; a new enum value needs a new revision.
    # Each enum is checked against the latest revision that names its values.
    first, second, fifth, eighth = _revision("0001_cluster_tables"), _revision("0002_campaigns"), _revision("0005_partial_campaigns"), _revision("0008_split_ardupilot_simulation")
    ninth, twelfth = _revision("0009_simulation_job_and_node_components"), _revision("0012_design_space_exploration")
    assert set(first.JOB_TYPES) == set(second.PREVIOUS_JOB_TYPES)
    assert set(second.JOB_TYPES) == set(eighth.PREVIOUS_JOB_TYPES)
    assert set(eighth.JOB_TYPES) == set(ninth.PREVIOUS_JOB_TYPES)
    assert set(ninth.JOB_TYPES) == set(twelfth.PREVIOUS_JOB_TYPES)
    assert set(twelfth.JOB_TYPES) == _values(JobType)
    assert set(first.JOB_STATES) == _values(JobState)
    assert set(first.NODE_STATUSES) == _values(NodeStatus)
    assert set(first.JOB_EVENT_KINDS) == _values(JobEventKind)
    assert set(second.CAMPAIGN_DESIRED_STATES) == _values(CampaignDesiredState)
    assert set(second.CAMPAIGN_ACTUAL_STATES) == _values(CampaignActualState)
    assert set(second.CAMPAIGN_CLASS_STATES) == _values(CampaignClassState)
    assert set(second.PIPELINE_STAGES) == set(fifth.PREVIOUS_PIPELINE_STAGES)
    assert set(fifth.PIPELINE_STAGES) == set(twelfth.PREVIOUS_PIPELINE_STAGES)
    assert set(twelfth.PIPELINE_STAGES) == _values(PipelineStage)
    assert set(second.CASE_STATES) == _values(CaseState)
    assert set(second.TRAJECTORY_GENERATORS) == _values(TrajectoryGeneratorImplementation)
    assert set(second.MONITORS) == _values(MonitorImplementation)
    assert set(second.VERDICT_STATES) == _values(VerdictState)
    assert set(second.CAMPAIGN_EVENT_KINDS) == _values(CampaignEventKind)
    assert set(second.ARTIFACT_HOLDER_KINDS) == set(fifth.PREVIOUS_ARTIFACT_HOLDER_KINDS)
    assert set(fifth.ARTIFACT_HOLDER_KINDS) == _values(ArtifactHolderKind)
    assert set(fifth.CAMPAIGN_KINDS) == _values(CampaignKind)
    assert set(fifth.CAMPAIGN_ORIGINS) == set(twelfth.PREVIOUS_CAMPAIGN_ORIGINS)
    assert set(twelfth.CAMPAIGN_ORIGINS) == _values(CampaignOrigin)
    assert set(fifth.STEP_KINDS) == _values(StepKind)
    assert set(fifth.RUN_SOURCES) == _values(RunSource)
    assert fifth.KIND_OF_ORIGIN == KIND_OF_ORIGIN_CHECK


def test_offline_upgrade_renders_the_tables(capsys):
    command.upgrade(alembic_config("postgresql://u:p@db/scenegems"), "head", sql=True)
    sql = capsys.readouterr().out
    for table in ALL_TABLES:
        assert f"CREATE TABLE {table} " in sql
    assert "WHERE state = 'queued'" in sql
    assert "ALTER TABLE job ADD COLUMN available_at" in sql
    assert "UPDATE job SET available_at = submitted_at" in sql
    assert "calibration.deviation" in sql
    assert "ALTER TABLE node ADD COLUMN machine VARCHAR(256)" in sql
    assert "ALTER TABLE job ADD COLUMN allowed_nodes JSONB DEFAULT '[]'::jsonb NOT NULL" in sql
    assert "UPDATE campaign SET kind = 'campaign'" in sql
    assert "UPDATE verdict SET step = 'simulation'" in sql
    assert "UPDATE run_record SET source = 'job'" in sql
    assert "'monitor_scene'" in sql and "'upload'" in sql
    assert "UPDATE job SET job_type = 'simulation.gazebo'" in sql and "'simulation.ardupilot_sim'" in sql
    assert "UPDATE job SET job_type = 'simulation', payload = jsonb_set(payload, '{runner}', '\"kinematic\"') WHERE job_type = 'simulation.kinematic'" in sql
    assert "ALTER TABLE job ADD COLUMN required_components JSONB DEFAULT '[]'::jsonb NOT NULL" in sql


@pytest.mark.postgres
def test_upgrade_on_an_empty_database(empty_database_url):
    upgrade_database(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == ALL_TABLES | {"alembic_version"}
        with engine.connect() as connection:
            assert MigrationContext.configure(connection).get_current_revision() == "0012"
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_upgraded_database_matches_the_tables(empty_database_url):
    upgrade_database(empty_database_url)
    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
        assert differences == []
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_upgrade_keeps_existing_jobs_available_since_their_submission(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0001")
    submitted = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
                    " idempotency_key, state, attempt, failed_attempts, submitted_at, updated_at)"
                    " VALUES ('job-1', 'scene_generation', '{}', '{}', '{}', 0, 0, 0, 3, 'key-1', 'queued', 0, 0, :at, :at)"
                ),
                {"at": submitted},
            )
            connection.execute(text("INSERT INTO job_event (job_id, at, kind, to_state, attempt, detail) VALUES ('job-1', :at, 'submitted', 'queued', 0, '{}')"), {"at": submitted})
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT available_at FROM job WHERE id = 'job-1'")).scalar_one() == submitted
            assert connection.execute(text("SELECT tx_id FROM job_event WHERE job_id = 'job-1'")).scalar_one() > 0
            # the new job type is accepted now
            connection.execute(text("UPDATE job SET job_type = 'calibration.deviation' WHERE id = 'job-1'"))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_the_machine_column_comes_and_goes_with_revision_0003(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0002")
    engine = create_engine(empty_database_url)
    registered = datetime(2026, 10, 26, 9, 30, tzinfo=timezone.utc)
    try:
        assert "machine" not in {column["name"] for column in inspect(engine).get_columns("node")}
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO node (id, name, status, labels, software_revision, cpus, memory_mb, free_memory_mb, free_disk_mb, load_average, registered_at, last_seen_at)"
                    " VALUES ('node-1', 'worker-1', 'online', '{}', 'abc', 4, 1000, 500, 5000, 0.1, :at, :at)"
                ),
                {"at": registered},
            )
        command.upgrade(config, "0003")
        columns = {column["name"]: column for column in inspect(engine).get_columns("node")}
        assert columns["machine"]["nullable"] and str(columns["machine"]["type"]) == "VARCHAR(256)"
        with engine.begin() as connection:
            assert connection.execute(text("SELECT machine FROM node WHERE id = 'node-1'")).scalar_one() is None  # nodes of before say hello again
            connection.execute(text("UPDATE node SET machine = 'lab-pc-3' WHERE id = 'node-1'"))
        command.downgrade(config, "0002")
        assert "machine" not in {column["name"] for column in inspect(engine).get_columns("node")}
        with engine.connect() as connection:
            assert connection.execute(text("SELECT name FROM node WHERE id = 'node-1'")).scalar_one() == "worker-1"  # the node stays
        command.upgrade(config, "head")
        assert "machine" in {column["name"] for column in inspect(engine).get_columns("node")}
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_jobs_of_before_revision_0004_may_run_on_any_node(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0003")
    submitted = datetime(2026, 10, 27, 9, 30, tzinfo=timezone.utc)
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
                    " idempotency_key, state, attempt, failed_attempts, submitted_at, available_at, updated_at)"
                    " VALUES ('job-1', 'scene_generation', '{}', '{}', '{}', 0, 0, 0, 3, 'key-1', 'queued', 0, 0, :at, :at, :at)"
                ),
                {"at": submitted},
            )
        command.upgrade(config, "0004")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT allowed_nodes FROM job WHERE id = 'job-1'")).scalar_one() == []
        command.downgrade(config, "0003")
        assert "allowed_nodes" not in {column["name"] for column in inspect(engine).get_columns("job")}
    finally:
        engine.dispose()


SHA = "e" * 64


def _insert_a_campaign_of_revision_0004(connection, at) -> None:
    """A campaign with one case, a run record, its verdict and an artifact reference, as revision 0004 holds them."""
    connection.execute(
        text(
            "INSERT INTO campaign (id, name, desired_state, actual_state, config_version, pinned_fingerprints, created_at, updated_at)"
            " VALUES ('c-1', 'before', 'running', 'running', 1, '{}', :at, :at)"
        ),
        {"at": at},
    )
    connection.execute(
        text(
            "INSERT INTO campaign_class (campaign_id, class_id, content_hash, vessel_count, obstacle_count, quota, failure_budget, complete_count, dropped_count,"
            " in_flight_count, state, created_at, updated_at) VALUES ('c-1', 'a/b', :sha, 2, 0, 1, 0, 0, 0, 1, 'open', :at, :at)"
        ),
        {"at": at, "sha": SHA},
    )
    case_id = connection.execute(
        text(
            "INSERT INTO scenario_case (campaign_id, class_id, case_index, seed, config_version, stage, state, version, progress, created_at, updated_at)"
            " VALUES ('c-1', 'a/b', 0, 7, 1, 'monitor', 'active', 1, '{}', :at, :at) RETURNING id"
        ),
        {"at": at},
    ).scalar_one()
    run_id = connection.execute(
        text(
            "INSERT INTO run_record (case_id, campaign_id, class_id, run_index, repeat_index, trajectory_generator, trajectories_complete, stack, environment, seed,"
            " artifacts, fingerprints, durations_s, created_at) VALUES (:case, 'c-1', 'a/b', 0, 0, 'straight', true, '{}', '{}', 7, '{}', '{}', '{}', :at) RETURNING id"
        ),
        {"at": at, "case": case_id},
    ).scalar_one()
    connection.execute(
        text(
            "INSERT INTO verdict (case_id, campaign_id, class_id, run_index, run_record_id, state, monitor, rule_outcomes, failed_rules, sensitive, created_at)"
            " VALUES (:case, 'c-1', 'a/b', 0, :run, 'passed', 'post_hoc', '{}', '[]', false, :at)"
        ),
        {"at": at, "case": case_id, "run": run_id},
    )
    connection.execute(text("INSERT INTO artifact (hash, kind, size_bytes, media_type, created_at, last_used_at) VALUES (:sha, 'scene', 3, 'application/json', :at, :at)"), {"at": at, "sha": SHA})
    connection.execute(
        text("INSERT INTO artifact_reference (artifact_hash, holder_kind, holder_id, role, campaign_id, created_at) VALUES (:sha, 'case', :case, 'scene', 'c-1', :at)"),
        {"at": at, "sha": SHA, "case": str(case_id)},
    )


@pytest.mark.postgres
def test_rows_of_before_revision_0005_become_full_chain_campaigns(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0004")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_campaign_of_revision_0004(connection, at)
        command.upgrade(config, "0005")
        with engine.begin() as connection:
            assert connection.execute(text("SELECT kind, origin FROM campaign")).one() == ("campaign", None)
            assert connection.execute(text("SELECT input_artifact, input_source FROM scenario_case")).one() == (None, None)
            assert connection.execute(text("SELECT step FROM verdict")).scalar_one() == "simulation"
            assert connection.execute(text("SELECT source, trajectory_generator FROM run_record")).one() == ("job", "straight")
            assert connection.execute(text("SELECT expires_at FROM artifact_reference")).scalar_one() is None
            # what the new revision allows: a scene verdict at run 0 beside the run's, a run without a generator, an upload that expires
            connection.execute(
                text(
                    "INSERT INTO verdict (case_id, campaign_id, class_id, step, run_index, state, monitor, rule_outcomes, failed_rules, sensitive, created_at)"
                    " SELECT case_id, campaign_id, class_id, 'scene', 0, 'passed', 'post_hoc', '{}', '[]', false, created_at FROM verdict"
                )
            )
            connection.execute(text("UPDATE run_record SET trajectory_generator = NULL, source = 'live_session'"))
            connection.execute(
                text("INSERT INTO artifact_reference (artifact_hash, holder_kind, holder_id, role, created_at, expires_at) VALUES (:sha, 'upload', :sha, 'upload', :at, :at)"),
                {"at": at, "sha": SHA},
            )
        for statement in (
            "UPDATE campaign SET origin = 'scene_generation'",  # a workbench origin on a campaign
            "UPDATE verdict SET run_index = 1 WHERE step = 'scene'",
            "UPDATE artifact_reference SET expires_at = NULL WHERE holder_kind = 'upload'",
            "UPDATE scenario_case SET input_artifact = 'not a hash'",
        ):
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(text(statement))
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_revision_0005_downgrades_while_its_rows_fit_revision_0004(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0004")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_campaign_of_revision_0004(connection, at)
        command.upgrade(config, "0005")
        with engine.begin() as connection:
            connection.execute(text("UPDATE campaign SET kind = 'workbench', origin = 'simulation'"))
            connection.execute(
                text(
                    "INSERT INTO verdict (case_id, campaign_id, class_id, step, run_index, state, monitor, rule_outcomes, failed_rules, sensitive, created_at)"
                    " SELECT case_id, campaign_id, class_id, 'trajectories', 0, 'passed', 'post_hoc', '{}', '[]', false, created_at FROM verdict"
                )
            )
        with pytest.raises(IntegrityError):  # a trajectory verdict has no place in revision 0004
            command.downgrade(config, "0004")
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM verdict WHERE step = 'trajectories'"))
        command.downgrade(config, "0004")
        with engine.connect() as connection:
            assert "kind" not in {column["name"] for column in inspect(engine).get_columns("campaign")}
            assert "step" not in {column["name"] for column in inspect(engine).get_columns("verdict")}
            assert connection.execute(text("SELECT count(*) FROM verdict")).scalar_one() == 1
            assert connection.execute(text("SELECT name FROM campaign")).scalar_one() == "before"  # a workbench entry stays as a campaign
        command.upgrade(config, "head")
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_downgrade_to_the_cluster_tables_and_upgrade_again(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    engine = create_engine(empty_database_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == CLUSTER_TABLES - {"node_component"} | {"alembic_version"}
        assert "available_at" not in {column["name"] for column in inspector.get_columns("job")}
        assert "tx_id" not in {column["name"] for column in inspector.get_columns("job_event")}
        command.upgrade(config, "head")
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_downgrade_to_base_and_upgrade_again(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(empty_database_url)
    try:
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_command_line_reads_the_environment(empty_database_url, monkeypatch):
    monkeypatch.setenv(DATABASE_URL_ENV, empty_database_url)
    main(["upgrade", "head"])
    engine = create_engine(empty_database_url)
    try:
        assert ALL_TABLES <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_the_setting_tables_come_and_go_with_revision_0006(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0005")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 29, 9, 30, tzinfo=timezone.utc)
    try:
        assert not {"cluster_domain", "campaign_preset"} & set(inspect(engine).get_table_names())
        command.upgrade(config, "0006")
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO cluster_domain (id, colregs_constants, vessel_types, obstacle_types, updated_at) VALUES (1, 'A: 1', 'B: 2', 'C: 3', :at)"), {"at": at})
        with pytest.raises(IntegrityError):  # one domain configuration per cluster
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO cluster_domain (id, colregs_constants, vessel_types, obstacle_types, updated_at) VALUES (2, 'A: 1', 'B: 2', 'C: 3', :at)"), {"at": at})
        command.downgrade(config, "0005")
        assert not {"cluster_domain", "campaign_preset"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_revision_0007_allows_an_unlimited_failure_budget_and_downgrades_without_one(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0004")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 29, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_campaign_of_revision_0004(connection, at)
        command.upgrade(config, "0007")
        with engine.begin() as connection:
            assert connection.execute(text("SELECT failure_budget FROM campaign_class")).scalar_one() == 0  # existing classes keep their numbers
            connection.execute(text("UPDATE campaign_class SET failure_budget = NULL"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text("UPDATE campaign_class SET failure_budget = -1"))
        with pytest.raises(IntegrityError):  # an unlimited budget has no place in revision 0006
            command.downgrade(config, "0006")
        with engine.begin() as connection:
            connection.execute(text("UPDATE campaign_class SET failure_budget = 3"))
        command.downgrade(config, "0006")
        assert not next(column for column in inspect(engine).get_columns("campaign_class") if column["name"] == "failure_budget")["nullable"]
        command.upgrade(config, "head")
    finally:
        engine.dispose()


def _insert_an_ardupilot_job(connection, job_id: str, layer: str, at) -> None:
    connection.execute(
        text(
            "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
            " idempotency_key, state, attempt, failed_attempts, submitted_at, available_at, updated_at)"
            " VALUES (:id, 'simulation.ardupilot', :payload, '{}', '{}', 0, 0, 0, 3, :id, 'queued', 0, 0, :at, :at, :at)"
        ),
        {"id": job_id, "payload": f'{{"simulation_layer": "{layer}"}}', "at": at},
    )


@pytest.mark.postgres
def test_revision_0008_splits_the_ardupilot_jobs_by_their_layer_and_drops_the_old_capability(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0007")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 29, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_an_ardupilot_job(connection, "on-sitl", "ardupilot_sim", at)
            _insert_an_ardupilot_job(connection, "on-gazebo", "gazebo", at)
            connection.execute(
                text(
                    "INSERT INTO node (id, name, status, labels, software_revision, cpus, memory_mb, free_memory_mb, free_disk_mb, load_average, registered_at, last_seen_at)"
                    " VALUES ('node-1', 'worker-1', 'online', '{}', 'abc', 4, 1000, 500, 5000, 0.1, :at, :at)"
                ),
                {"at": at},
            )
            connection.execute(text("INSERT INTO node_capability (node_id, job_type, slots, slots_in_use) VALUES ('node-1', 'simulation.ardupilot', 1, 0), ('node-1', 'simulation.kinematic', 2, 0)"))
        command.upgrade(config, "0008")
        with engine.begin() as connection:
            job_types = dict(connection.execute(text("SELECT id, job_type FROM job")).all())
            assert job_types == {"on-sitl": "simulation.ardupilot_sim", "on-gazebo": "simulation.gazebo"}
            capabilities = connection.execute(text("SELECT job_type FROM node_capability WHERE node_id = 'node-1'")).scalars().all()
            assert capabilities == ["simulation.kinematic"], "the node lists its capabilities again in its Hello"
            connection.execute(text("INSERT INTO node_capability (node_id, job_type, slots, slots_in_use) VALUES ('node-1', 'simulation.gazebo', 1, 0)"))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE job SET job_type = 'simulation.ardupilot' WHERE id = 'on-sitl'"))
        command.downgrade(config, "0007")
        with engine.connect() as connection:
            assert set(connection.execute(text("SELECT job_type FROM job")).scalars().all()) == {"simulation.ardupilot"}
            assert connection.execute(text("SELECT job_type FROM node_capability WHERE node_id = 'node-1'")).scalars().all() == ["simulation.kinematic"]
    finally:
        engine.dispose()


def _insert_a_simulation_job(connection, job_id: str, job_type: str, payload: str, at) -> None:
    connection.execute(
        text(
            "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
            " idempotency_key, state, attempt, failed_attempts, submitted_at, available_at, updated_at, allowed_nodes)"
            " VALUES (:id, :job_type, :payload, '{}', '{}', 0, 0, 0, 3, :id, 'queued', 0, 0, :at, :at, :at, '[]')"
        ),
        {"id": job_id, "job_type": job_type, "payload": payload, "at": at},
    )


@pytest.mark.postgres
def test_revision_0009_merges_the_simulation_jobs_by_their_runner_and_stores_node_components(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0008")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_simulation_job(connection, "kinematic", "simulation.kinematic", '{"mode": "replay"}', at)
            _insert_a_simulation_job(connection, "sitl", "simulation.ardupilot_sim", '{"simulation_layer": "ardupilot_sim"}', at)
            _insert_a_simulation_job(connection, "world", "simulation.gazebo", '{"simulation_layer": "gazebo"}', at)
            _insert_a_simulation_job(connection, "scene", "scene_generation", '{"seed": 1}', at)
            connection.execute(
                text(
                    "INSERT INTO node (id, name, status, labels, software_revision, cpus, memory_mb, free_memory_mb, free_disk_mb, load_average, registered_at, last_seen_at)"
                    " VALUES ('node-1', 'worker-1', 'online', '{}', 'abc', 4, 1000, 500, 5000, 0.1, :at, :at)"
                ),
                {"at": at},
            )
            connection.execute(
                text(
                    "INSERT INTO node_capability (node_id, job_type, slots, slots_in_use) VALUES ('node-1', 'simulation.kinematic', 2, 0), ('node-1', 'simulation.gazebo', 1, 0), ('node-1', 'scene_generation', 1, 0)"
                )
            )
        command.upgrade(config, "0009")
        with engine.begin() as connection:
            jobs = {row.id: (row.job_type, row.payload, row.required_components) for row in connection.execute(text("SELECT id, job_type, payload, required_components FROM job"))}
            assert jobs == {
                "kinematic": ("simulation", {"mode": "replay", "runner": "kinematic"}, []),
                "sitl": ("simulation", {"simulation_layer": "ardupilot_sim", "runner": "ardupilot"}, []),
                "world": ("simulation", {"simulation_layer": "gazebo", "runner": "ardupilot"}, []),
                "scene": ("scene_generation", {"seed": 1}, []),
            }
            capabilities = connection.execute(text("SELECT job_type FROM node_capability WHERE node_id = 'node-1'")).scalars().all()
            assert capabilities == ["scene_generation"], "the node lists its slots again in its Hello"
            connection.execute(text("INSERT INTO node_capability (node_id, job_type, slots, slots_in_use) VALUES ('node-1', 'simulation', 2, 0)"))
            connection.execute(text("INSERT INTO node_component (node_id, component) VALUES ('node-1', 'simulation_layer/kinematic')"))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE job SET job_type = 'simulation.kinematic' WHERE id = 'kinematic'"))
        command.downgrade(config, "0008")
        with engine.connect() as connection:
            jobs = {row.id: (row.job_type, row.payload) for row in connection.execute(text("SELECT id, job_type, payload FROM job"))}
            assert jobs == {
                "kinematic": ("simulation.kinematic", {"mode": "replay"}),
                "sitl": ("simulation.ardupilot_sim", {"simulation_layer": "ardupilot_sim"}),
                "world": ("simulation.gazebo", {"simulation_layer": "gazebo"}),
                "scene": ("scene_generation", {"seed": 1}),
            }
            assert connection.execute(text("SELECT job_type FROM node_capability WHERE node_id = 'node-1'")).scalars().all() == ["scene_generation"]
            assert "node_component" not in inspect(connection).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_revision_0010_adds_nullable_encounters_that_existing_verdicts_lack(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0004")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_campaign_of_revision_0004(connection, at)
        command.upgrade(config, "0009")
        assert "encounters" not in {column["name"] for column in inspect(engine).get_columns("verdict")}
        command.upgrade(config, "0010")
        columns = {column["name"]: column for column in inspect(engine).get_columns("verdict")}
        assert columns["encounters"]["nullable"] and type(columns["encounters"]["type"]).__name__ == "JSONB"
        with engine.begin() as connection:
            assert connection.execute(text("SELECT encounters IS NULL FROM verdict")).scalar_one(), "an existing verdict has no encounters (SQL NULL, not a JSON null)"
            connection.execute(text("""UPDATE verdict SET encounters = '{"OS_0 - TS_1": ["HEAD_ON"]}'"""))
        command.downgrade(config, "0009")
        assert "encounters" not in {column["name"] for column in inspect(engine).get_columns("verdict")}
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_revision_0011_adds_nullable_encounter_roles_that_existing_verdicts_lack(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0004")
    engine = create_engine(empty_database_url)
    at = datetime(2026, 11, 4, 9, 30, tzinfo=timezone.utc)
    try:
        with engine.begin() as connection:
            _insert_a_campaign_of_revision_0004(connection, at)
        command.upgrade(config, "0010")
        assert "encounter_roles" not in {column["name"] for column in inspect(engine).get_columns("verdict")}
        command.upgrade(config, "0011")
        columns = {column["name"]: column for column in inspect(engine).get_columns("verdict")}
        assert columns["encounter_roles"]["nullable"] and type(columns["encounter_roles"]["type"]).__name__ == "JSONB"
        with engine.begin() as connection:
            assert connection.execute(text("SELECT encounter_roles IS NULL FROM verdict")).scalar_one(), "an existing verdict has no roles (SQL NULL, not a JSON null)"
            connection.execute(text("""UPDATE verdict SET encounter_roles = '{"OS_0 - TS_1": {"HEAD_ON": {"give_way": ["OS_0", "TS_1"], "stand_on": []}}}'"""))
        command.downgrade(config, "0010")
        assert "encounter_roles" not in {column["name"] for column in inspect(engine).get_columns("verdict")}
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_the_design_space_exploration_values_come_and_go_with_revision_0012(empty_database_url):
    config = alembic_config(empty_database_url)
    command.upgrade(config, "0011")
    engine = create_engine(empty_database_url)
    now = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
    job = (
        "INSERT INTO job (id, job_type, payload, required_labels, required_fingerprints, min_memory_mb, min_cpus, priority, max_attempts,"
        " idempotency_key, state, attempt, failed_attempts, submitted_at, updated_at, available_at)"
        " VALUES (:id, :job_type, '{}', '{}', '{}', 0, 0, 0, 3, :id, 'queued', 0, 0, :at, :at, :at)"
    )
    campaign = (
        "INSERT INTO campaign (id, name, kind, origin, desired_state, actual_state, config_version, pinned_fingerprints, created_at, updated_at)"
        " VALUES (:id, 'explore', :kind, :origin, 'running', 'created', 1, '{}', :at, :at)"
    )
    campaign_class = (
        "INSERT INTO campaign_class (campaign_id, class_id, content_hash, vessel_count, obstacle_count, quota, failure_budget, complete_count, dropped_count, in_flight_count, state, created_at, updated_at)"
        " VALUES (:campaign, :class_id, :hash, :vessels, 0, 1, 0, 0, 0, 0, 'open', :at, :at)"
    )
    case = (
        "INSERT INTO scenario_case (campaign_id, class_id, case_index, seed, config_version, stage, state, version, progress, created_at, updated_at)"
        " VALUES (:campaign, :class_id, 0, 1, 1, :stage, 'active', 1, '{}', :at, :at)"
    )
    explored = {"campaign": "explored", "class_id": "exploration", "hash": "a" * 64, "vessels": 0, "at": now}
    try:
        with engine.connect() as connection:  # before the revision none of the new values is accepted
            for statement, values in (
                (job, {"id": "job-old", "job_type": "design_space_exploration", "at": now}),
                (campaign, {"id": "old", "kind": "workbench", "origin": "design_space_exploration", "at": now}),
            ):
                with pytest.raises(IntegrityError):
                    connection.execute(text(statement), values)
                connection.rollback()
        command.upgrade(config, "0012")
        with engine.begin() as connection:
            connection.execute(text(job), {"id": "job-explore", "job_type": "design_space_exploration", "at": now})
            connection.execute(text(job), {"id": "job-scene", "job_type": "scene_generation", "at": now})
            connection.execute(text(campaign), {"id": "explored", "kind": "campaign", "origin": "wizard", "at": now})
            connection.execute(text(campaign), {"id": "entry", "kind": "workbench", "origin": "design_space_exploration", "at": now})
            connection.execute(text(campaign), {"id": "plain", "kind": "campaign", "origin": "wizard", "at": now})
            connection.execute(text(campaign_class), explored)
            connection.execute(text(campaign_class), {**explored, "campaign": "plain", "class_id": "2vessel_0obstacle_scenarios/fec0", "vessels": 2})
            connection.execute(text(case), {"campaign": "explored", "class_id": "exploration", "stage": "explore_design_space", "at": now})
        command.downgrade(config, "0011")
        with engine.connect() as connection:  # what an older release cannot read is gone, the rest stays
            assert connection.execute(text("SELECT id FROM campaign ORDER BY id")).scalars().all() == ["plain"]
            assert connection.execute(text("SELECT id FROM job ORDER BY id")).scalars().all() == ["job-scene"]
            assert connection.execute(text("SELECT count(*) FROM scenario_case")).scalar_one() == 0
            with pytest.raises(IntegrityError):
                connection.execute(text(campaign_class), {**explored, "campaign": "plain", "class_id": "exploration"})
            connection.rollback()
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text(campaign_class), {**explored, "campaign": "plain", "class_id": "exploration"})
    finally:
        engine.dispose()
