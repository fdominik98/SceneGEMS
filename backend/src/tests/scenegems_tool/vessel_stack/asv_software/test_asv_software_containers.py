"""ASV software behind the wire protocol: the replay and USV Navigation servers answer as their in-process participants do."""

import subprocess
import sys

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_software.asv_software_link import AsvSoftwareLink
from scenegems_tool.vessel_stack.asv_software.asv_software_runtime import ParticipantRequest, asv_software_runtime, vessel_limits
from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.asv_software.replay.replay_server import ReplaySession
from scenegems_tool.vessel_stack.asv_software.usv_navigation import usv_navigation_server
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import parameters_for
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_participant import UsvNavigationParticipant
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server import UsvNavigationSession
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SOFTWARE, Endpoint, LineServer, WireError
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories


@pytest.fixture(scope="module")
def head_on():
    return encounter_trajectories("head_on", 60)


def request_for(trajectories, asv_software=AsvSoftwareId.REPLAY, control_layer=ControlLayerId.NONE, simulation_layer=SimulationLayerId.KINEMATIC) -> ParticipantRequest:
    vessel = trajectories.initial_scene.vessels[0]
    stack = VesselStackConfig(asv_software=asv_software, control_layer=control_layer, simulation_layer=simulation_layer)
    parameters = parameters_for(vessel, trajectories, 1.0) if asv_software == AsvSoftwareId.USV_NAVIGATION else None
    return ParticipantRequest(vessel, "vessel_0", asv_software, default_resolver().resolve(stack).asv_adapter, trajectories, 1.0, parameters)


def served(session_factory, implementation, request) -> AsvSoftwareLink:
    server = LineServer(ROLE_ASV_SOFTWARE, implementation, session_factory, host="127.0.0.1").start_in_thread()
    link = AsvSoftwareLink(Endpoint("127.0.0.1", server.port), request).connect(5.0)
    link.server = server  # closed by the test
    return link


def off_track_observations(trajectories, steps=25):
    """The own ship drifting off its reference, so the followers' corrections are exercised, with the target on its own."""
    own, target = trajectories.initial_scene.vessels
    for index in range(steps):
        reference = trajectories.state_list(own)[index]
        state = ActorState(reference.x - 0.7 * index, reference.y + 1.3 * index, reference.speed * 0.9, reference.heading + 0.01 * index)
        yield StepRequest(index, float(index), float(index + 1)), VesselStateObservation(float(index), own, state, {target.id: trajectories.state_list(target)[index]})


class TestReplay:
    def test_the_container_commands_what_the_follower_in_process_commands(self, head_on):
        request = request_for(head_on)
        local = asv_software_runtime(AsvSoftwareId.REPLAY).in_process(request)
        assert isinstance(local, ReplayFollower)
        link = served(ReplaySession, "replay", request)
        local.start(3)
        link.start(3)
        assert link.participant_id == local.participant_id == "replay/0" and link.mission is None
        for step, observation in off_track_observations(head_on):
            assert link.on_step(step, observation) == local.on_step(step, observation)
        assert link.report() == {}
        link.close()
        link.server.close()

    def test_towards_the_custom_controller_it_hands_over_its_trajectory_as_the_mission(self, head_on):
        request = request_for(head_on, control_layer=ControlLayerId.CUSTOM, simulation_layer=SimulationLayerId.GAZEBO)
        assert request.hands_over_mission
        assert isinstance(asv_software_runtime(AsvSoftwareId.REPLAY).in_process(request), LosWaypointFollower), "in process the controller's follower is the participant"
        link = served(ReplaySession, "replay", request)
        link.start(0)
        reference = head_on.state_list(request.vessel)
        assert link.mission["time_step"] == 1.0
        assert link.mission["waypoints"] == [[state.x, state.y, state.speed, state.heading] for state in reference]
        link.close()
        link.server.close()

    def test_a_container_running_other_software_is_refused(self, head_on):
        link = served(UsvNavigationSession, "usv_navigation", request_for(head_on))  # a replay request against a USV Navigation server
        with pytest.raises(WireError, match="KeyError"):
            link.start(0)
        link.server.close()


class TestUsvNavigation:
    def test_the_container_commands_what_the_participant_in_process_commands(self):
        trajectories = encounter_trajectories("overtaking", 300)
        request = request_for(trajectories, AsvSoftwareId.USV_NAVIGATION)
        local = asv_software_runtime(AsvSoftwareId.USV_NAVIGATION).in_process(request)
        assert isinstance(local, UsvNavigationParticipant)
        link = served(UsvNavigationSession, "usv_navigation", request)
        local.start(0)
        link.start(0)
        assert link.participant_id == local.participant_id == "usv_navigation/0"
        own, target = trajectories.initial_scene.vessels
        own_state = trajectories.initial_scene[own]
        for index in range(150):
            step = StepRequest(index, float(index), float(index + 1))
            observation = VesselStateObservation(float(index), own, own_state, {target.id: trajectories.state_list(target)[index]})
            command = local.on_step(step, observation)
            assert link.on_step(step, observation) == command
            own_state = own.simulate(own_state, (command.heading, command.speed), 1.0)
        assert local.transitions, "the overtaking makes the automaton act within the run"
        assert link.report() == local.report() == {"transitions": [list(transition) for transition in local.transitions], "goal_reached_at": None}
        link.close()
        link.server.close()

    def test_the_parameters_are_required(self, head_on):
        request = request_for(head_on)
        with pytest.raises(ValueError, match="needs UsvNavigationParameters"):
            asv_software_runtime(AsvSoftwareId.USV_NAVIGATION).start_config(request)

    def test_the_server_needs_nothing_of_scenegems_but_the_wire_protocol(self):
        """The USV Navigation image holds this file, lockstep_wire.py, numpy and colav_automaton only."""
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "import scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server;"
            "print(sorted(name for name in sys.modules if name.split('.')[0] in ('scenegems_tool', 'concrete_level', 'utils', 'colav_automaton') and not name.endswith('__init__')))"
        )
        source_root = usv_navigation_server.__file__.split("scenegems_tool")[0]
        modules = eval(subprocess.run([sys.executable, "-c", code, source_root], capture_output=True, text=True, check=True).stdout)
        leaves = {"lockstep_wire", "usv_navigation_server"}
        assert {name for name in modules if name.rsplit(".", 1)[-1] in leaves} == {
            "scenegems_tool.vessel_stack.contracts.lockstep_wire",
            "scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server",
        }
        packages = {
            "scenegems_tool",
            "scenegems_tool.vessel_stack",
            "scenegems_tool.vessel_stack.contracts",
            "scenegems_tool.vessel_stack.asv_software",
            "scenegems_tool.vessel_stack.asv_software.usv_navigation",
        }
        assert set(modules) - packages == {
            "scenegems_tool.vessel_stack.contracts.lockstep_wire",
            "scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server",
        }, "no SceneGEMS model, no utils, and colav_automaton only once a run starts"


class TestRuntimes:
    def test_the_vessel_block_holds_what_any_software_may_need(self, head_on):
        vessel = head_on.initial_scene.vessels[0]
        assert vessel_limits(vessel) == {"id": 0, "length": 30.0, "max_speed": vessel.max_speed, "max_acceleration": vessel.max_acceleration, "max_angular_speed": vessel.max_angular_speed}

    @pytest.mark.parametrize("software", [AsvSoftwareId.MISSION_PLANNER, AsvSoftwareId.ON_BOARD])
    def test_software_no_lockstep_runner_steps_has_no_runtime(self, software):
        with pytest.raises(LookupError, match="is not stepped by a lockstep runner"):
            asv_software_runtime(software)
