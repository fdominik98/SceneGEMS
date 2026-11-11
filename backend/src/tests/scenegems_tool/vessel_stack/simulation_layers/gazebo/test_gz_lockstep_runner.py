"""gz lockstep runner: participants, autopilots and the stepped world on one clock, against a fake link whose hulls are the surge-yaw model."""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import reference_run
from scenegems_tool.vessel_stack.calibration.repeat_analysis import TrackSamples, tracking_error
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, TwinThrustAutopilot
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_runner
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import sdf_value
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import (
    FLUID_DENSITY,
    gz_custom_instance,
    hull_dynamics,
    run_gz_custom,
    run_gz_lockstep,
    thruster_constants,
)
from tests.scenegems_tool.vessel_stack.scenarios import stack_instance
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_hull_link import FakeHullLink

CALM = EnvironmentConfig.calm()


def straight_run():
    trajectories = reference_run("straight", "30m", 30, from_rest=True)
    return trajectories, trajectories.initial_scene.vessels[0]


def setup_run(trajectories, vessel, late_steps=()):
    dynamics = hull_dynamics(vessel, CALM)
    initial = trajectories.initial_scene[vessel]
    link = FakeHullLink({"os": (HullSurgeYawModel(dynamics), HullState(initial.x, initial.y, initial.heading, 0.0, 0.0, 0.0))}, late_steps)
    participants = {0: LosWaypointFollower(vessel, trajectories.state_list(vessel), trajectories.time_step)}
    autopilots = {0: TwinThrustAutopilot(AutopilotGains.from_dynamics(dynamics, vessel, 0.1))}
    return link, participants, autopilots, {0: thruster_constants(dynamics)}


def run(trajectories, vessel, late_steps=(), **kwargs):
    link, participants, autopilots, thrusters = setup_run(trajectories, vessel, late_steps)
    result = run_gz_lockstep(link, {0: "os"}, participants, autopilots, {0: vessel}, thrusters, 1.0, 30, 7, **kwargs)
    return link, result


class TestRunGzLockstep:
    def test_the_world_settles_then_steps_every_control_step(self):
        trajectories, vessel = straight_run()
        link, result = run(trajectories, vessel)
        assert link.started[1:] == (5_000_000, 400), "2 s of 5 ms iterations"
        assert link.steps == 300, "30 scenario steps of ten 0.1 s control steps"
        assert result.epoch_sim_time_ns == 2_000_000_000
        assert result.steps == 30 and len(result.states) == 31 and len(result.odometry) == 301
        assert result.participant_seeds[0][0] == "replay/0"

    def test_the_vessel_follows_its_reference(self):
        trajectories, vessel = straight_run()
        _, result = run(trajectories, vessel)
        states = [step[0] for step in result.states]
        track = TrackSamples(
            time_s=np.arange(len(states), dtype=float),
            x=np.array([state.x for state in states]),
            y=np.array([state.y for state in states]),
            speed=np.array([state.speed for state in states]),
        )
        summary = tracking_error(track, trajectories.state_list(vessel), 1.0, settle_s=0.0)
        assert max(abs(state.y) for state in states) < 1e-9, "the eastbound hull has nothing to turn it"
        assert abs(summary.final_along_track_m) < 0.5
        assert summary.max_along_track_lag_m < 0.5

    def test_the_same_inputs_give_the_same_digest(self):
        trajectories, vessel = straight_run()
        assert run(trajectories, vessel)[1].state_digest() == run(trajectories, vessel)[1].state_digest()

    def test_late_thrust_commands_are_counted(self):
        trajectories, vessel = straight_run()
        assert run(trajectories, vessel, late_steps={3, 40})[1].late_commands == 2

    def test_the_observer_sees_every_scenario_step(self):
        trajectories, vessel = straight_run()
        seen = []
        run(trajectories, vessel, on_step=lambda index, states: seen.append((index, sorted(states))))
        assert seen == [(index, [0]) for index in range(31)]

    def test_dt_must_be_whole_control_steps(self):
        trajectories, vessel = straight_run()
        link, participants, autopilots, thrusters = setup_run(trajectories, vessel)
        with pytest.raises(ValueError, match="whole number of control steps"):
            run_gz_lockstep(link, {0: "os"}, participants, autopilots, {0: vessel}, thrusters, 0.25, 4, 7)


class TestHull:
    def test_thruster_constants_are_the_sdfs(self):
        _, vessel = straight_run()
        dynamics = hull_dynamics(vessel, CALM)
        assert thruster_constants(dynamics) == {
            "thrust_coefficient": sdf_value(dynamics.thrust_coefficient),
            "propeller_diameter": sdf_value(dynamics.propeller_diameter),
            "fluid_density": FLUID_DENSITY,
            "max_thrust": sdf_value(dynamics.max_thrust),
        }


class TestGzCustom:
    def test_the_instance_runs_every_vessel_on_the_custom_controller(self):
        trajectories, _ = straight_run()
        instance = gz_custom_instance(trajectories, {0: AsvSystemId.USV_NAVIGATION}, speedup=2)
        vessel = instance.vessels["0"]
        assert (vessel.stack.asv_system, vessel.stack.control_layer, vessel.stack.simulation_layer) == (AsvSystemId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)
        assert vessel.connection.agent_name == "os"
        assert gz_custom_instance(trajectories).vessels["0"].stack.asv_system == AsvSystemId.REPLAY

    def test_run_gz_custom_drives_the_registry_participants_and_records_the_run(self, monkeypatch):
        trajectories, vessel = straight_run()
        links = []

        def fake_link(host, port):
            assert (host, port) == ("gazebo", 11400)
            link = setup_run(trajectories, vessel)[0]
            links.append(link)
            return link

        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", fake_link)
        result = run_gz_custom(trajectories, gz_custom_instance(trajectories), steps=5)
        assert result.steps == 5 and links[0].closed
        record = result.run_record
        assert {"custom_controller_waypoint_follower", "gz_transport_actuator"} <= set(record["specs"])
        assert record["late_commands"] == 0
        assert record["state_digest"] == result.state_digest()
        assert record["control_dt"] == 0.1 and record["physics_step_s"] == 0.005

    def test_run_gz_custom_needs_the_custom_control_layer(self, monkeypatch):
        trajectories, _ = straight_run()
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", lambda host, port: pytest.fail("no link before the stack is valid"))
        with pytest.raises(StackUnavailableError):
            run_gz_custom(trajectories, stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.ARDUPILOT))

    def test_usv_navigation_drives_the_custom_controller(self, monkeypatch):
        trajectories, vessel = straight_run()
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", lambda host, port: setup_run(trajectories, vessel)[0])
        result = run_gz_custom(trajectories, gz_custom_instance(trajectories, {0: AsvSystemId.USV_NAVIGATION}), steps=20)
        record = result.run_record
        assert "custom_controller_heading_speed_input" in record["specs"]
        assert dict(result.participant_seeds).keys() == {"usv_navigation/0"}
        assert record["usv_navigation"]["0"]["goal"] == [trajectories.state_list(vessel)[-1].x, 0.0]
        assert result.states[-1][0].x > 10.0, "the vessel heads for its goal east"
