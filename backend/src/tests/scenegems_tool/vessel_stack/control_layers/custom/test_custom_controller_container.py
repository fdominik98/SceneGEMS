"""The custom controller behind the wire protocol: its container gives the actuator commands and setpoints of the classes in process, and so the same Gazebo run."""

import dataclasses
import math

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.calibration.reference_scenarios import reference_run, scaled_vessel
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_CONTROLLER, Endpoint, LineServer, WireError
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_link import CustomControllerLink
from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server import CustomControllerSession
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, HullObservation, TwinThrustAutopilot
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_runner
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import gz_custom_instance, hull_dynamics, run_gz_custom
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_hosting
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_hull_link import FakeHullLink

CALM = EnvironmentConfig.calm()


@pytest.fixture(scope="module")
def run():
    trajectories = reference_run("straight", "30m", 30, from_rest=True)
    return trajectories, trajectories.initial_scene.vessels[0]


@pytest.fixture
def controller(run):
    _, vessel = run
    gains = AutopilotGains.from_dynamics(hull_dynamics(vessel, CALM), vessel, 0.1)
    with LineServer(ROLE_CONTROLLER, "custom", CustomControllerSession, host="127.0.0.1") as server:
        link = CustomControllerLink(Endpoint("127.0.0.1", server.port), vessel, gains).connect(5.0)
        yield link, TwinThrustAutopilot(gains)
        link.close()


def test_the_container_gives_the_autopilots_thrusts(controller):
    link, autopilot = controller
    link.reset()
    autopilot.reset()
    for index in range(60):  # a turn demand large enough to saturate the yaw loop, then settling
        hull = HullObservation(heading=0.02 * index, surge=0.05 * index, yaw_rate=0.001 * index)
        desired_heading, desired_speed = math.pi / 2 if index < 30 else 0.5, 6.0
        command = link.command(desired_heading, desired_speed, hull, 0.1)
        assert command == autopilot.command(desired_heading, desired_speed, hull, 0.1)
        assert len(command.thrusts) == 2 and command.helm_angle is None, "port and starboard thrust, and no helm on a skid steered hull"


def steered_vessel(steering: str):
    return dataclasses.replace(scaled_vessel("30m"), _steering_type=steering)


@pytest.mark.parametrize("steering", ["rudder", "vectored_thrust"])
def test_the_container_gives_the_thrust_and_the_helm_angle_of_a_hull_with_a_helm(steering):
    """Every field of the command, bit for bit: the thrust, the helm angle, the force and moment it gives and the saturation flags."""
    vessel = steered_vessel(steering)
    gains = AutopilotGains.from_dynamics(hull_dynamics(vessel, CALM), vessel, 0.1)
    autopilot = TwinThrustAutopilot(gains)
    with LineServer(ROLE_CONTROLLER, "custom", CustomControllerSession, host="127.0.0.1") as server:
        link = CustomControllerLink(Endpoint("127.0.0.1", server.port), vessel, gains).connect(5.0)
        link.reset()
        commands = []
        for index in range(90):  # a turn to port, a turn back while slowing down (vectored thrust goes astern), then settling
            hull = HullObservation(heading=0.02 * index, surge=6.0 - 0.05 * index, yaw_rate=0.02 * math.sin(0.2 * index), sway=-0.3 * math.sin(0.2 * index))
            desired_heading, desired_speed = (math.pi / 2, 6.0) if index < 30 else (-0.5, 1.0) if index < 60 else (0.02 * index, 3.0)
            command = link.command(desired_heading, desired_speed, hull, 0.1)
            assert command == autopilot.command(desired_heading, desired_speed, hull, 0.1)
            commands.append(command)
        link.close()
    assert all(len(command.thrusts) == 1 and isinstance(command.helm_angle, float) for command in commands)
    assert min(command.helm_angle for command in commands) < -0.1 and max(command.helm_angle for command in commands) > 0.1
    assert any(command.yaw_saturated for command in commands) and any(not command.yaw_saturated for command in commands)


def test_the_hulls_sway_reaches_the_controller():
    """A rudder's allocation reads the sway: the same step with and without it gives another helm angle."""
    vessel = steered_vessel("rudder")
    gains = AutopilotGains.from_dynamics(hull_dynamics(vessel, CALM), vessel, 0.1)
    with LineServer(ROLE_CONTROLLER, "custom", CustomControllerSession, host="127.0.0.1") as server:
        link = CustomControllerLink(Endpoint("127.0.0.1", server.port), vessel, gains).connect(5.0)
        link.reset()
        straight = link.command(0.01, 8.0, HullObservation(0.0, 8.0, 0.0, 0.0), 0.1)
        link.reset()
        drifting = link.command(0.01, 8.0, HullObservation(0.0, 8.0, 0.0, -0.5), 0.1)
        link.close()
    assert drifting.helm_angle < straight.helm_angle


def test_a_reset_starts_the_integrators_again(controller):
    link, autopilot = controller
    hull = HullObservation(heading=0.0, surge=0.0, yaw_rate=0.0)
    link.reset()
    first = [link.command(1.0, 5.0, hull, 0.1) for _ in range(10)]
    link.reset()
    assert [link.command(1.0, 5.0, hull, 0.1) for _ in range(10)] == first


def test_with_a_mission_the_controller_guides_itself_as_its_waypoint_follower_does(controller, run):
    link, _ = controller
    trajectories, vessel = run
    reference = trajectories.state_list(vessel)
    follower = LosWaypointFollower(vessel, reference, trajectories.time_step)
    follower.start(5)
    link.load_mission({"time_step": float(trajectories.time_step), "waypoints": [[state.x, state.y, state.speed, state.heading] for state in reference]}, seed=5)
    link.reset()
    for index in range(20):
        state = reference[index].modify_copy(y=reference[index].y + 0.4 * index)  # drifting to port of the path
        step = StepRequest(index, float(index), float(index + 1))
        observation = VesselStateObservation(float(index), vessel, state, {})
        assert link.guide(step, observation) == follower.on_step(step, observation)


def test_guiding_needs_a_mission(controller, run):
    link, _ = controller
    _, vessel = run
    link.reset()
    with pytest.raises(WireError, match="guide needs a start with a waypoint mission"):
        link.guide(StepRequest(0, 0.0, 1.0), VesselStateObservation(0.0, vessel, run[0].initial_scene[vessel], {}))


def fake_gazebo(monkeypatch, trajectories, vessel):
    """The gz-transport actuator replaced by the surge and yaw model of the vessel's hull."""
    initial = trajectories.initial_scene[vessel]

    def link(host, port):
        return FakeHullLink({"os": (HullSurgeYawModel(hull_dynamics(vessel, CALM)), HullState(initial.x, initial.y, initial.heading, 0.0, 0.0, 0.0))}, ())

    monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", link)


@pytest.mark.parametrize("steering", ["rudder", "vectored_thrust"])
def test_a_gazebo_run_of_a_hull_with_a_helm_in_containers_is_the_run_in_process(monkeypatch, steering):
    """The gains with the steering gear and the commands with the helm angle cross the wire without a bit lost."""
    vessel = steered_vessel(steering)
    trajectories = TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: ActorState(0.0, 0.0, 8.0, 0.3)}), 1, 30)
    fake_gazebo(monkeypatch, trajectories, vessel)
    instance = gz_custom_instance(trajectories)
    in_process = run_gz_custom(trajectories, instance, steps=30)
    with loopback_hosting(instance) as hosting:
        contained = run_gz_custom(trajectories, instance, steps=30, hosting=hosting)
    assert contained.state_digest() == in_process.state_digest(), "every control step's odometry, bit for bit"
    assert contained.run_record["steering_types"] == in_process.run_record["steering_types"] == {"0": steering}
    assert contained.states[-1][0].x > 10.0 and contained.states[-1][0].heading > 0.02, "the vessel moved and turned toward its path"


@pytest.mark.parametrize("asv_system", [AsvSystemId.REPLAY, AsvSystemId.USV_NAVIGATION])
def test_a_gazebo_run_with_every_layer_in_its_container_is_the_run_in_process(monkeypatch, run, asv_system):
    trajectories, vessel = run
    fake_gazebo(monkeypatch, trajectories, vessel)
    instance = gz_custom_instance(trajectories, {0: asv_system})
    in_process = run_gz_custom(trajectories, instance, steps=30)
    with loopback_hosting(instance) as hosting:
        contained = run_gz_custom(trajectories, instance, steps=30, hosting=hosting)
    assert contained.state_digest() == in_process.state_digest(), "every control step's odometry, bit for bit"
    assert contained.participant_seeds == in_process.participant_seeds
    stable = {key: value for key, value in in_process.run_record.items() if key != "achieved_speedup"}
    assert {key: value for key, value in contained.run_record.items() if key != "achieved_speedup"} == stable
    assert contained.states[-1][0].x > 10.0, "the vessel moved"
