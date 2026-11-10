import pytest

from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryJobStore, InMemoryWorkerNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def memory_plane() -> ControlPlane:
    """A control plane on the in-memory stores, for routes that read no database."""
    clock = ManualClock()
    worker_nodes = InMemoryWorkerNodeStore(clock)
    return ControlPlane("lab-control-node", worker_nodes, InMemoryJobStore(worker_nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
