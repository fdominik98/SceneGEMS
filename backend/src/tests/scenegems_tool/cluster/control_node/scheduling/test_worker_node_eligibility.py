from dataclasses import replace

import pytest

from scenegems_tool.cluster.control_node.scheduling.worker_node_eligibility import Ineligibility, ResourceGuard, ineligibility
from scenegems_tool.persistence.schema import WorkerNodeStatus
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryWorkerNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello, make_resources

GUARD = ResourceGuard(min_free_memory_mb=512, max_load_average=1.5)


USABLE = frozenset({"scene_generation"})


def _worker_node(status=WorkerNodeStatus.ONLINE, free_memory_mb=8000, load_average=0.2):
    record = InMemoryWorkerNodeStore(ManualClock()).register(make_hello("worker-node-a", components=["scene_generation", "monitoring"]))
    return replace(record, status=status, resources=make_resources(free_memory_mb=free_memory_mb).model_copy(update={"load_average": load_average}))


def test_an_online_up_to_date_worker_node_with_room_is_eligible():
    assert ineligibility(_worker_node(), usable_components=USABLE, fingerprints_known=True, guard=GUARD) is None


@pytest.mark.parametrize("status", [WorkerNodeStatus.DRAINING, WorkerNodeStatus.OFFLINE])
def test_only_online_worker_nodes(status):
    assert ineligibility(_worker_node(status=status), USABLE, True, GUARD) == Ineligibility.NOT_ONLINE


def test_nothing_is_leased_while_the_expected_fingerprints_are_unknown():
    assert ineligibility(_worker_node(), USABLE, False, GUARD) == Ineligibility.FINGERPRINTS_UNKNOWN


def test_out_of_date_once_no_component_is_usable():
    assert ineligibility(_worker_node(), frozenset(), True, GUARD) == Ineligibility.OUT_OF_DATE


def test_resource_guard_bounds():
    assert ineligibility(_worker_node(free_memory_mb=511), USABLE, True, GUARD) == Ineligibility.LOW_MEMORY
    assert ineligibility(_worker_node(free_memory_mb=512), USABLE, True, GUARD) is None
    assert ineligibility(_worker_node(load_average=1.51), USABLE, True, GUARD) == Ineligibility.OVERLOADED
    assert ineligibility(_worker_node(load_average=1.5), USABLE, True, GUARD) is None
