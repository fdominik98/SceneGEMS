from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.worker_node_description import SlotOffer, WorkerNodeResources
from scenegems_tool.cluster.worker_node.daemon.control.status_frames import UNKNOWN_REVISION, StatusFrames, software_revision

RESOURCES = WorkerNodeResources(cpus=8.0, memory_mb=16000, free_memory_mb=9000, free_disk_mb=50000, load_average=0.25)


class Leases:
    def running_lease_ids(self):
        return ["lease-2", "lease-7"]

    def slots_in_use(self):
        return {JobType.SIMULATION: 2}


def frames(fingerprints=lambda: {"image:latest": "abc"}, machine=None) -> StatusFrames:
    return StatusFrames(
        worker_node_id="worker-1-abc123",
        worker_node_name="worker-1",
        software_revision="0123abc",
        slots={JobType.SIMULATION: 4, JobType.MONITORING_POST_HOC: 1},
        components=frozenset({"monitoring", "simulation_layer/kinematic", "asv_software/replay", "control_layer/none"}),
        labels={"site": "lab"},
        resources=lambda: RESOURCES,
        fingerprints=fingerprints,
        leases=Leases(),
        machine=machine,
    )


def test_hello_names_the_worker_node_its_slots_images_and_running_leases():
    hello = frames().hello()
    assert (hello.worker_node_id, hello.worker_node_name, hello.software_revision) == ("worker-1-abc123", "worker-1", "0123abc")
    assert hello.slots == [SlotOffer(job_type=JobType.MONITORING_POST_HOC, slots=1), SlotOffer(job_type=JobType.SIMULATION, slots=4)]
    assert hello.components == ["asv_software/replay", "control_layer/none", "simulation_layer/kinematic", "monitoring"], "in catalog order"
    assert hello.labels == {"site": "lab"} and hello.resources == RESOURCES
    assert hello.fingerprints == {"image:latest": "abc"}
    assert hello.running_lease_ids == ["lease-2", "lease-7"]


def test_hello_names_the_machine_when_there_is_one():
    assert frames(machine="lab-pc-3").hello().machine == "lab-pc-3"
    assert frames().hello().machine is None


def test_hello_without_docker_reports_no_fingerprints():
    def unreachable():
        raise ConnectionError("no Docker socket")

    assert frames(unreachable).hello().fingerprints == {}


def test_heartbeat_reports_slots_in_use_and_running_leases():
    heartbeat = frames().heartbeat()
    assert heartbeat.resources == RESOURCES
    assert heartbeat.slots_in_use == {JobType.SIMULATION: 2}
    assert heartbeat.running_lease_ids == ["lease-2", "lease-7"]


def test_the_configured_revision_is_reported():
    assert software_revision("v1.2") == "v1.2"


def test_without_a_configured_revision_the_worker_node_reports_unknown():
    assert software_revision(None) == UNKNOWN_REVISION
    assert software_revision("") == UNKNOWN_REVISION
