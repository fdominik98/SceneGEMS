import re

"""A master on a test client: control plane, node API and operator routes, with scripted nodes.

The `stores` fixture runs each test that uses it twice: on the in-memory stores (default
run) and on a real Postgres (`-m postgres`). Timers are off: tests run the scheduler and
the sweeps themselves, on the app's event loop, after moving the manual clock.
"""

from dataclasses import dataclass
from typing import Callable, Collection, Dict, Iterator, Optional

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.fingerprints.comparison import by_repository
from scenegems_tool.cluster.fingerprints.components import MONITORING_IMAGE, SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE, TRAJECTORY_GENERATION_IMAGE
from scenegems_tool.cluster.master.api.master_apps import create_node_api_app
from scenegems_tool.cluster.master.api.operator_routes import operator_router
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.stores import JobStore, NodeStore
from tests.scenegems_tool.cluster.master.fake_node import FakeNode
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

# The master's expected fingerprints in these tests as release.json names the images; a node built from the same checkout reports them
EXPECTED = {
    SCENE_GENERATION_IMAGE: "fp-scene",
    TRAJECTORY_GENERATION_IMAGE: "fp-trajectory",
    SCENARIO_EXECUTION_IMAGE: "fp-execution",
    MONITORING_IMAGE: "fp-monitoring",
    SITL_IMAGE: "fp-sitl",
    GAZEBO_IMAGE: "fp-gazebo",
    "scenegems-master-api:latest": "fp-master-api",
}
# The same as the master holds and requires them: by image repository (cluster/fingerprints/comparison.py)
EXPECTED_BY_REPOSITORY = by_repository(EXPECTED)
SCENE = JobType.SCENE_GENERATION
KINEMATIC = JobType.SIMULATION  # with valid_payload, the kinematic runner


@dataclass
class Stores:
    nodes: object
    jobs: object


def _slug(name: str) -> str:
    """A node id part from a display name: lowercase letters, digits and hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-") or "node"


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.postgres)])
def stores(request, clock) -> Stores:
    if request.param == "memory":
        nodes = InMemoryNodeStore(clock)
        return Stores(nodes, InMemoryJobStore(nodes, clock))
    session_factory = request.getfixturevalue("session_factory")
    return Stores(NodeStore(session_factory, clock), JobStore(session_factory, clock))


@pytest.fixture
def plane(stores, clock) -> ControlPlane:
    return ControlPlane("lab-master", stores.nodes, stores.jobs, ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def client(plane) -> Iterator[TestClient]:
    app = create_node_api_app(plane, run_timers=False)
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
def make_node(client) -> Iterator[Callable[..., FakeNode]]:
    """A scripted node of the master. Its id is its name's slug and a counter, so two nodes of one name stay apart."""
    nodes = []

    def make(
        name: str,
        slots: Optional[Dict[JobType, int]] = None,
        labels=None,
        fingerprints: Optional[Dict[str, str]] = None,
        resources=None,
        machine: Optional[str] = None,
        components: Optional[Collection[str]] = None,
    ) -> FakeNode:
        """components: every component of the catalog when None."""
        node_id = f"{_slug(name)}-{len(nodes) + 1}"
        hello = make_hello(
            node_id,
            slots=slots or {SCENE: 2},
            labels=labels,
            fingerprints=dict(EXPECTED) if fingerprints is None else fingerprints,
            resources=resources,
            name=name,
            machine=machine,
            components=components,
        )
        nodes.append(FakeNode(client, hello))
        return nodes[-1]

    yield make
    # An open socket would keep the test client's event loop from stopping
    for node in nodes:
        node.close()
