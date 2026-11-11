import re

"""A control node on a test client: control plane, worker node API and operator routes, with scripted worker nodes.

The `stores` fixture runs each test that uses it twice: on the in-memory stores (default
run) and on a real Postgres (`-m postgres`). Timers are off: tests run the scheduler and
the sweeps themselves, on the app's event loop, after moving the manual clock.
"""

from dataclasses import dataclass
from typing import Callable, Collection, Dict, Iterator, Optional

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_worker_node_api_app
from scenegems_tool.cluster.control_node.api.operator_routes import operator_router
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.fingerprints.comparison import by_repository
from scenegems_tool.cluster.fingerprints.components import MONITORING_IMAGE, SCENE_GENERATION_IMAGE, SIMULATION_IMAGE, TRAJECTORY_GENERATION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.stores import JobStore, WorkerNodeStore
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryJobStore, InMemoryWorkerNodeStore
from tests.scenegems_tool.cluster.control_node.fake_worker_node import FakeWorkerNode
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

# The control node's expected fingerprints in these tests as release.json names the images; a worker node built from the same checkout reports them
EXPECTED = {
    SCENE_GENERATION_IMAGE: "fp-scene",
    TRAJECTORY_GENERATION_IMAGE: "fp-trajectory",
    SIMULATION_IMAGE: "fp-execution",
    MONITORING_IMAGE: "fp-monitoring",
    SITL_IMAGE: "fp-sitl",
    GAZEBO_IMAGE: "fp-gazebo",
    "scenegems-control-node-api:latest": "fp-control-node-api",
}
# The same as the control node holds and requires them: by image repository (cluster/fingerprints/comparison.py)
EXPECTED_BY_REPOSITORY = by_repository(EXPECTED)
SCENE = JobType.SCENE_GENERATION
KINEMATIC = JobType.SIMULATION  # with valid_payload, the kinematic runner


@dataclass
class Stores:
    worker_nodes: object
    jobs: object


def _slug(name: str) -> str:
    """A worker node id part from a display name: lowercase letters, digits and hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "worker-node"


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def stores(request, clock) -> Stores:
    if request.param == "memory":
        worker_nodes = InMemoryWorkerNodeStore(clock)
        return Stores(worker_nodes, InMemoryJobStore(worker_nodes, clock))
    session_factory = request.getfixturevalue("session_factory")
    return Stores(WorkerNodeStore(session_factory, clock), JobStore(session_factory, clock))


@pytest.fixture
def plane(stores, clock) -> ControlPlane:
    return ControlPlane("lab-control-node", stores.worker_nodes, stores.jobs, ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def client(plane) -> Iterator[TestClient]:
    app = create_worker_node_api_app(plane, run_timers=False)
    app.include_router(operator_router(plane))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def on_loop(client) -> Callable:
    """Runs a coroutine function of the control plane on the app's event loop, as its timers would."""

    def call(function, *arguments):
        return client.portal.call(function, *arguments)

    return call


@pytest.fixture
def schedule(on_loop, plane) -> Callable[[], int]:
    return lambda: on_loop(plane.scheduler.run_once)


@pytest.fixture
def make_worker_node(client) -> Iterator[Callable[..., FakeWorkerNode]]:
    """A scripted worker node of the control node. Its id is its name's slug and a counter, so two worker nodes of one name stay apart."""
    worker_nodes = []

    def make(
        name: str,
        slots: Optional[Dict[JobType, int]] = None,
        labels=None,
        fingerprints: Optional[Dict[str, str]] = None,
        resources=None,
        machine: Optional[str] = None,
        components: Optional[Collection[str]] = None,
    ) -> FakeWorkerNode:
        """components: every component of the catalog when None."""
        worker_node_id = f"{_slug(name)}-{len(worker_nodes) + 1}"
        hello = make_hello(
            worker_node_id,
            slots=slots or {SCENE: 2},
            labels=labels,
            fingerprints=dict(EXPECTED) if fingerprints is None else fingerprints,
            resources=resources,
            name=name,
            machine=machine,
            components=components,
        )
        worker_nodes.append(FakeWorkerNode(client, hello))
        return worker_nodes[-1]

    yield make
    # An open socket would keep the test client's event loop from stopping
    for worker_node in worker_nodes:
        worker_node.close()
