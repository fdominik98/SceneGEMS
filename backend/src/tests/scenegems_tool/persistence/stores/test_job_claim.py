from sqlalchemy.dialects import postgresql

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.stores.job_claim import free_job_types, next_queued_job_query
from tests.scenegems_tool.persistence.stores.builders import START

SCENE = JobType.SCENE_GENERATION
TRAJECTORY = JobType.TRAJECTORY_GENERATION
KINEMATIC = JobType.SIMULATION


def test_free_job_types_need_a_free_slot():
    slots = {SCENE: 2, TRAJECTORY: 1, KINEMATIC: 4}
    assert free_job_types(slots, {SCENE: 2, TRAJECTORY: 0, KINEMATIC: 3}) == [TRAJECTORY, KINEMATIC]


def test_free_job_types_ignore_leases_of_types_the_worker_node_does_not_offer():
    assert free_job_types({SCENE: 1}, {KINEMATIC: 5}) == [SCENE]


def test_free_job_types_can_be_limited():
    assert free_job_types({SCENE: 1, TRAJECTORY: 1}, {}, only=[TRAJECTORY]) == [TRAJECTORY]
    assert free_job_types({SCENE: 1}, {}, only=[KINEMATIC]) == []


def _compiled_query() -> str:
    query = next_queued_job_query([SCENE], {"site": "lab"}, {"scenegems-scene-generation": "f1"}, free_memory_mb=4000, cpus=4.0, now=START, worker_node_id="worker-node-1")
    return str(query.compile(dialect=postgresql.dialect()))


def test_claim_query_skips_locked_rows():
    sql = _compiled_query()
    assert sql.rstrip().endswith("LIMIT %(param_1)s FOR UPDATE SKIP LOCKED")


def test_claim_query_orders_by_priority_then_submission():
    assert "ORDER BY job.priority DESC, job.submitted_at, job.seq" in _compiled_query()


def test_claim_query_filters_in_sql():
    sql = _compiled_query()
    assert "job.state = %(state_1)s" in sql
    assert "job.available_at <= %(available_at_1)s" in sql
    assert "job.job_type IN" in sql
    assert "job.required_labels <@ %(required_labels_1)s::JSONB" in sql
    assert "job.required_components <@ %(required_components_1)s::JSONB" in sql
    assert "job.required_fingerprints <@ %(required_fingerprints_1)s::JSONB" in sql
    assert "job.min_memory_mb <= %(min_memory_mb_1)s" in sql
    assert "job.min_cpus <= %(min_cpus_1)s" in sql
    assert "(job.allowed_worker_nodes = %(allowed_worker_nodes_1)s::JSONB OR (job.allowed_worker_nodes @> %(allowed_worker_nodes_2)s::JSONB))" in sql


def test_claim_query_excludes_held_back_jobs_only_when_asked():
    assert "NOT IN" not in _compiled_query()
    query = next_queued_job_query([SCENE], {}, {}, free_memory_mb=4000, cpus=4.0, exclude_job_ids=["job-a", "job-b"], now=START, worker_node_id="worker-node-1")
    assert "job.id NOT IN (__[POSTCOMPILE_id_1])" in str(query.compile(dialect=postgresql.dialect()))


def test_claim_query_binds_the_worker_nodes_components():
    params = (
        next_queued_job_query([SCENE], {}, {}, free_memory_mb=4000, cpus=4.0, now=START, worker_node_id="worker-node-7", components=["scene_generation"]).compile(dialect=postgresql.dialect()).params
    )
    assert params["required_components_1"] == ["scene_generation"]


def test_claim_query_binds_the_worker_node_for_allowed_worker_nodes():
    params = next_queued_job_query([SCENE], {}, {}, free_memory_mb=4000, cpus=4.0, now=START, worker_node_id="worker-node-7").compile(dialect=postgresql.dialect()).params
    assert params["allowed_worker_nodes_1"] == []
    assert params["allowed_worker_nodes_2"] == ["worker-node-7"]
