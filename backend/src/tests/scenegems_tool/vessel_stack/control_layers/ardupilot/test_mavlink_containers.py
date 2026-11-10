"""The MAVLink lockstep runner with every vessel's ASV software in its container: the run it gives in process."""

import pytest

from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import mavlink_instance, run_mavlink_stack
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from tests.scenegems_tool.vessel_stack.control_layers.ardupilot.fake_sitl import FakeLink
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_hosting
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories


@pytest.fixture(autouse=True)
def isolated_fake_state():
    FakeLink.start_positions = {0: (0.0, 0.0), 1: (6000.0, 0.0)}
    FakeLink.connections = []
    yield
    FakeLink.start_positions = {}
    FakeLink.connections = []


@pytest.fixture
def resolver():
    registry = build_registry()
    registry.bind_runtime("replay_mavlink_lockstep", lambda: FakeLink)
    registry.bind_runtime("usv_navigation_mavlink_lockstep", lambda: FakeLink)
    return StackResolver(registry)


@pytest.mark.parametrize("own_ship", [AsvSoftwareId.REPLAY, AsvSoftwareId.USV_NAVIGATION])
def test_the_run_with_asv_software_containers_is_the_run_in_process(resolver, own_ship):
    trajectories = encounter_trajectories("head_on", 30)
    instance = mavlink_instance(trajectories, SimulationLayerId.ARDUPILOT_SIM, {0: own_ship})
    in_process = run_mavlink_stack(trajectories, instance, GEOFENCE, resolver=resolver, steps=30)
    with loopback_hosting(instance) as hosting:
        contained = run_mavlink_stack(trajectories, instance, GEOFENCE, resolver=resolver, steps=30, hosting=hosting)
    assert contained.state_digest() == in_process.state_digest()
    assert contained.participant_seeds == in_process.participant_seeds
    assert set(dict(contained.participant_seeds)) == {f"{own_ship.value}/0", "replay/1"}
    stable = {key: value for key, value in in_process.run_record.items() if key != "achieved_speedup"}
    assert {key: value for key, value in contained.run_record.items() if key != "achieved_speedup"} == stable


def test_the_asv_software_is_reached_before_sitl_is_engaged(resolver):
    """SITL runs free once its link connects, so a missing ASV software container must fail the run before that."""
    from scenegems_tool.vessel_stack.contracts.lockstep_wire import WireError
    from scenegems_tool.vessel_stack.hosting import ContainerHosting

    trajectories = encounter_trajectories("head_on", 30)
    instance = mavlink_instance(trajectories, SimulationLayerId.ARDUPILOT_SIM)
    with loopback_hosting(instance) as hosting:
        endpoints = dict(hosting._endpoints)
    with pytest.raises(WireError, match="no asv_software at"):
        run_mavlink_stack(trajectories, instance, GEOFENCE, resolver=resolver, steps=30, hosting=ContainerHosting(endpoints, connect_timeout_s=0.3))
    assert FakeLink.connections == [], "no SITL link was connected"
