import math

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


def _vessel(vessel_id: int, is_os: bool, length: float = 30.0) -> ConcreteActor:
    return ConcreteActor.from_dict(
        {
            "id": vessel_id,
            "type": "OSPassengerShip" if is_os else "PassengerShip",
            "length": length,
            "breadth": length / 3,
            "safety_radius": 4 * length,
            "is_vessel": True,
            "_is_os": is_os,
            "_max_speed": 20.57778,
            "_max_angular_speed": 0.05,
            "_max_acceleration": 0.4,
        }
    )


@pytest.fixture
def head_on_trajectories() -> Trajectories:
    """Two vessels on reciprocal straight courses, 3 km apart, 120 s at 1 s steps."""
    scene = ConcreteScene({_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), _vessel(1, False): ActorState(3000.0, 0.0, 8.0, math.pi)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 120)


@pytest.fixture
def worker_node() -> WorkerNodeContext:
    return WorkerNodeContext(
        control_node_id="m1",
        worker_node_id="n1",
        mqtt_connection=MQttConnectionInfo("worker-node", "secret", "broker", "localhost", 1883, False, False),
        reference_geofence=Geofence(57.7, 11.9, 2000.0),
        slots={JobType.SCENE_GENERATION: 3, JobType.SIMULATION: 2},
    )


@pytest.fixture
def make_job():
    """Build a leased job of a type with a payload."""

    def make(job_type: JobType, payload: dict, job_id: str = "job-1", attempt: int = 1) -> JobSpec:
        return JobSpec(job_id=job_id, job_type=job_type, payload=payload, attempt=attempt, idempotency_key=f"{job_id}/key")

    return make
