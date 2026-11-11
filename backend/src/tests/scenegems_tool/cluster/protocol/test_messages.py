import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import (
    DEFAULT_OBSERVED_SPEED,
    MAX_OBSERVATION_FRAMES,
    MAX_OBSERVED_SPEED,
    Hello,
    JobStatus,
    LeaseAccept,
    ObservationFrames,
    Observe,
    Welcome,
)
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION
from scenegems_tool.cluster.protocol.worker_node_description import SlotOffer


def test_frames_carry_the_protocol_version():
    assert LeaseAccept(lease_id="l1").protocol_version == PROTOCOL_VERSION


def test_frame_of_another_version_does_not_validate():
    with pytest.raises(ValidationError, match="Incompatible cluster protocol version"):
        LeaseAccept(lease_id="l1", protocol_version=PROTOCOL_VERSION + 1)


def test_frames_are_immutable():
    frame = LeaseAccept(lease_id="l1")
    with pytest.raises(ValidationError):
        frame.lease_id = "l2"


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        LeaseAccept(lease_id="l1", lease="l1")


def test_a_slot_offer_needs_a_slot():
    with pytest.raises(ValidationError):
        SlotOffer(job_type=JobType.SCENE_GENERATION, slots=0)


def test_hello_lists_slots_and_components(resources):
    hello = Hello(
        worker_node_id="n1",
        worker_node_name="lab-1",
        software_revision="4ac7ef2",
        slots=[SlotOffer(job_type=JobType.SIMULATION, slots=4)],
        components=["asv_system/replay", "control_layer/none", "simulation_layer/kinematic"],
        resources=resources,
    )
    assert hello.slots[0].slots == 4 and hello.components[2] == "simulation_layer/kinematic"
    assert hello.running_lease_ids == []
    with pytest.raises(ValidationError, match="components"):
        Hello(worker_node_id="n1", worker_node_name="lab-1", software_revision="4ac7ef2", slots=[], resources=resources)
    with pytest.raises(ValidationError, match="capabilities"):
        Hello(worker_node_id="n1", worker_node_name="lab-1", software_revision="4ac7ef2", slots=[], components=[], capabilities=[], resources=resources)


def test_hello_names_the_machine_optionally(resources):
    base = dict(
        worker_node_id="n1", worker_node_name="lab-1", software_revision="4ac7ef2", slots=[SlotOffer(job_type=JobType.SCENE_GENERATION, slots=1)], components=["scene_generation"], resources=resources
    )
    assert Hello(**base).machine is None
    hello = Hello(**base, machine="lab-pc-3")
    assert Hello.model_validate_json(hello.model_dump_json()).machine == "lab-pc-3"


def test_progress_is_a_fraction():
    with pytest.raises(ValidationError):
        JobStatus(lease_id="l1", job_id="j1", progress=1.5)


def test_welcome_needs_positive_intervals():
    with pytest.raises(ValidationError):
        Welcome(control_node_id="m1", instance_number=1, heartbeat_interval_s=0.0, lease_timeout_s=30.0)


def test_observe_defaults_to_ten_times_real_time_within_bounds():
    observe = Observe(job_id="j1", attempt=1, active=True)
    assert observe.speed == DEFAULT_OBSERVED_SPEED == 10.0
    assert Observe(job_id="j1", attempt=1, active=True, speed=MAX_OBSERVED_SPEED).speed == 1000.0
    for speed in (0.0, -1.0, MAX_OBSERVED_SPEED + 1):
        with pytest.raises(ValidationError):
            Observe(job_id="j1", attempt=1, active=True, speed=speed)
    with pytest.raises(ValidationError):
        Observe(job_id="j1", attempt=0, active=False)


def test_observation_frames_come_in_bounded_non_empty_batches():
    frame = {"scenarioId": "j1", "timestamp": 0}
    batch = ObservationFrames(lease_id="l1", job_id="j1", attempt=2, seq=1, frames=[frame] * MAX_OBSERVATION_FRAMES)
    assert (batch.attempt, batch.seq, len(batch.frames)) == (2, 1, 200)
    for frames in ([], [frame] * (MAX_OBSERVATION_FRAMES + 1)):
        with pytest.raises(ValidationError):
            ObservationFrames(lease_id="l1", job_id="j1", attempt=1, seq=1, frames=frames)
    with pytest.raises(ValidationError):
        ObservationFrames(lease_id="l1", job_id="j1", attempt=1, seq=0, frames=[frame])
