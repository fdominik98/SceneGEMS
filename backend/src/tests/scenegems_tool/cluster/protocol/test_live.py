"""The live channel's contract: messages, update data and topic names (version 1)."""

from datetime import datetime, timezone

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.live import (
    JOB_INSTANCE_KINDS,
    LIVE_PATH,
    LIVE_VERSION,
    CampaignChanged,
    CampaignDeleted,
    CampaignEventAdded,
    CampaignFecsChanged,
    CampaignRowChanged,
    Configure,
    Error,
    InstanceKind,
    InstanceSnapshot,
    InstanceStatus,
    InvalidLiveMessage,
    InvalidTopic,
    JobChanged,
    JobLogsAdded,
    JobProgressView,
    JobStatusChanged,
    Ping,
    Pong,
    SceneSample,
    SimulationFrames,
    Subscribe,
    Subscribed,
    TopicKind,
    TopicOptions,
    TrajectoryPreview,
    Unsubscribe,
    Unsubscribed,
    Update,
    WorkerNodeChanged,
    WorkerNodeRemoved,
    campaign_topic,
    campaigns_topic,
    decode_client_message,
    decode_server_message,
    instance_topic,
    is_rated,
    job_instance,
    job_topic,
    parse_instance,
    parse_topic,
)


def test_the_channel_lives_on_the_operator_api_at_version_1():
    assert LIVE_PATH == "/cluster/live" and LIVE_VERSION == 1


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"version": 1, "type": "subscribe", "topic": "worker_nodes"}', Subscribe(topic="worker_nodes")),
        ('{"version": 1, "type": "unsubscribe", "topic": "job:abc"}', Unsubscribe(topic="job:abc")),
        ('{"version": 1, "type": "ping"}', Ping()),
        ('{"version": 1, "type": "subscribe", "topic": "instance:n1/job-a-1", "options": {"speed": 25}}', Subscribe(topic="instance:n1/job-a-1", options=TopicOptions(speed=25.0))),
        ('{"version": 1, "type": "configure", "topic": "instance:n1/job-a-1", "options": {"speed": 0.5}}', Configure(topic="instance:n1/job-a-1", options=TopicOptions(speed=0.5))),
    ],
)
def test_client_messages_decode(text, expected):
    assert decode_client_message(text) == expected


@pytest.mark.parametrize(
    "text, reason",
    [
        ("not json", "not JSON"),
        ("[1]", "JSON object"),
        ('{"type": "ping"}', "version"),
        ('{"version": 2, "type": "ping"}', "version 2"),
        ('{"version": 1, "type": "publish", "topic": "worker_nodes"}', "invalid publish"),
        ('{"version": 1, "type": "subscribe"}', "invalid subscribe"),
        ('{"version": 1, "type": "ping", "extra": 1}', "invalid ping"),
        ('{"version": 1, "type": "subscribe", "topic": "worker_nodes", "options": {"speed": 0}}', "invalid subscribe"),
        ('{"version": 1, "type": "configure", "topic": "instance:n1/job-a-1", "options": {"speed": 1001}}', "invalid configure"),
        ('{"version": 1, "type": "configure", "topic": "instance:n1/job-a-1"}', "invalid configure"),
        ('{"version": 1, "type": "subscribe", "topic": "worker_nodes", "options": {"pace": 2}}', "invalid subscribe"),
    ],
)
def test_bad_client_messages_are_refused_with_a_reason(text, reason):
    with pytest.raises(InvalidLiveMessage, match=reason):
        decode_client_message(text)


def test_server_messages_round_trip():
    messages = [
        Subscribed(topic="worker_nodes", snapshot=[{"worker_node_id": "n1"}]),
        Update(topic="job:a", seq=3, data={"logs": []}),
        Unsubscribed(topic="worker_nodes"),
        Error(message="unknown topic", topic="bogus"),
        Error(message="not JSON"),
        Pong(),
    ]
    for message in messages:
        text = message.model_dump_json()
        assert '"version":1' in text
        assert decode_server_message(text) == message
    with pytest.raises(ValueError):
        Update(topic="worker_nodes", seq=0, data={})  # seq counts from 1


def test_update_data_shapes():
    at = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
    assert WorkerNodeChanged(worker_node={"worker_node_id": "n1"}).model_dump() == {"worker_node": {"worker_node_id": "n1"}}
    assert WorkerNodeRemoved(removed="n1").model_dump() == {"removed": "n1"}
    assert CampaignEventAdded(event={"event_id": 4}).model_dump() == {"event": {"event_id": 4}}
    assert CampaignChanged(campaign={"actual_state": "running"}).model_dump() == {"campaign": {"actual_state": "running"}}
    assert CampaignFecsChanged(fecs=[{"fec_id": "a"}]).model_dump() == {"fecs": [{"fec_id": "a"}]}
    assert CampaignRowChanged(campaign={"campaign_id": "c1", "totals": {}}).model_dump() == {"campaign": {"campaign_id": "c1", "totals": {}}}
    assert CampaignDeleted(deleted="c1").model_dump() == {"deleted": "c1"}
    status = JobStatusChanged(status=JobProgressView(progress=0.5, message="half", at=at)).model_dump(mode="json")
    assert status == {"status": {"progress": 0.5, "message": "half", "at": "2026-10-26T12:00:00Z"}}
    assert JobLogsAdded(logs=[{"text": "x"}]).model_dump() == {"logs": [{"text": "x"}]}
    assert JobChanged(job={"state": "running"}).model_dump() == {"job": {"state": "running"}}


def test_instance_updates_carry_their_kind():
    sample = SceneSample(request_id="r1", valid=True, scene={"scenarioId": "r1"}, evaluation_data={"best_fitness": [0.1]})
    preview = TrajectoryPreview(request_id="r2", trajectories={"trajectories": []})
    result = TrajectoryPreview(request_id="r2", final=True, valid=True, complete=False)
    frames = SimulationFrames(job_id="j1", frames=[{"timestamp": 0}])
    status = InstanceStatus(state="running", message="step 4", progress=0.4)
    kinds = [update.model_dump()["kind"] for update in (sample, preview, result, frames, status)]
    assert kinds == ["scene_sample", "trajectory_preview", "trajectory_preview", "simulation_frames", "status"]
    assert status.model_dump()["observed_speed"] is None and InstanceStatus(state="running", observed_speed=20.0).model_dump()["observed_speed"] == 20.0
    assert sample.model_dump()["final"] is False and result.model_dump()["complete"] is False


def test_previews_and_frames_are_rated_but_final_results_and_status_are_not():
    assert is_rated(SceneSample(request_id="r", valid=False))
    assert not is_rated(SceneSample(request_id="r", valid=True, final=True))
    assert is_rated(TrajectoryPreview(request_id="r"))
    assert not is_rated(TrajectoryPreview(request_id="r", final=True))
    assert is_rated(SimulationFrames(job_id="j", frames=[]))
    assert not is_rated(InstanceStatus(state="running"))


def test_instance_snapshot():
    snapshot = InstanceSnapshot(worker_node_id="n1", instance="job-abc-1", kind=InstanceKind.SIMULATION, state="running", job_id="abc", attempt=1)
    assert snapshot.model_dump(mode="json") == {"worker_node_id": "n1", "instance": "job-abc-1", "kind": "simulation", "state": "running", "job_id": "abc", "attempt": 1, "observed_speed": None}
    observed = InstanceSnapshot(worker_node_id="n1", instance="job-abc-1", kind=InstanceKind.SIMULATION, state="running", job_id="abc", attempt=1, observed_speed=25.0)
    assert observed.model_dump(mode="json")["observed_speed"] == 25.0


def test_every_job_type_has_an_instance_kind():
    assert set(JOB_INSTANCE_KINDS) == set(JobType)
    assert JOB_INSTANCE_KINDS[JobType.MONITORING_POST_HOC] == InstanceKind.MONITORING


# Topics


def test_topic_names_parse_back():
    job_id = "6f1c2b9e-1d2a-4c3b-9a8e-0f1e2d3c4b5a"
    assert parse_topic("worker_nodes").kind == TopicKind.WORKER_NODES and parse_topic("worker_nodes").name == "worker_nodes"
    campaigns = parse_topic(campaigns_topic())
    assert (campaigns.kind, campaigns.key, campaigns.name) == (TopicKind.CAMPAIGNS, "", "campaigns") and campaigns_topic() == "campaigns"
    campaign = parse_topic(campaign_topic("c-17"))
    assert (campaign.kind, campaign.key, campaign.name) == (TopicKind.CAMPAIGN, "c-17", "campaign:c-17")
    job = parse_topic(job_topic(job_id))
    assert (job.kind, job.key) == (TopicKind.JOB, job_id)
    instance = parse_topic(instance_topic("lab-1", job_instance(job_id, 2)))
    assert (instance.kind, instance.worker_node_id, instance.instance) == (TopicKind.INSTANCE, "lab-1", f"job-{job_id}-2")
    assert instance.name == f"instance:lab-1/job-{job_id}-2"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "worker_node",
        "campaign",
        "campaigns:c1",
        "campaign:",
        "job:",
        "job:has space",
        "instance:",
        "instance:lab-1",
        "instance:Lab/scene_generation-0",
        "instance:lab-1/unknown-0",
        "instance:lab-1/job-abc",
        "instance:lab-1/job-abc-0",
        "#",
    ],
)
def test_bad_topics_are_refused(text):
    with pytest.raises(InvalidTopic):
        parse_topic(text)


def test_instance_names():
    pool = parse_instance("trajectory_generation-0")
    assert pool.kind == InstanceKind.TRAJECTORY_GENERATION and not pool.is_job
    job = parse_instance("job-6f1c2b9e-1d2a-4c3b-9a8e-0f1e2d3c4b5a-3")
    assert job.is_job and job.job_id == "6f1c2b9e-1d2a-4c3b-9a8e-0f1e2d3c4b5a" and job.attempt == 3 and job.kind is None
