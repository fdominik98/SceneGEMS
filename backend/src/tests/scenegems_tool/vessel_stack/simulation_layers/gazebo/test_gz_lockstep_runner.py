"""gz lockstep runner: participants, autopilots and the stepped world on one clock, against a fake link whose hulls are the surge-yaw model."""

import dataclasses

import numpy as np
import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.calibration.reference_scenarios import reference_run, scaled_vessel
from scenegems_tool.vessel_stack.calibration.repeat_analysis import TrackSamples, tracking_error
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, TwinThrustAutopilot
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_runner
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import UnknownVesselModelPreset, VesselOutOfPresetBounds
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


def steered_run(steering: str):
    """The 30 m vessel with that steering type on a straight reference at its cruise speed; the hull starts at rest."""
    vessel = dataclasses.replace(scaled_vessel("30m"), _steering_type=steering)
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: ActorState(0.0, 0.0, 8.0, 0.0)}), 1, 30), vessel


def panamax_run():
    """A Panamax container ship with a rudder, within the bounds of the shipped preset hanjin_pretoria."""
    vessel = dataclasses.replace(
        scaled_vessel("100m"), length=266.0, breadth=35.5, draft=12.2, height=30.5, _steering_type="rudder", _block_coefficient=0.65, _max_speed=12.86, _max_angular_speed=0.007
    )
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: ActorState(0.0, 0.0, 8.0, 0.0)}), 1, 30), vessel


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

    def test_the_actuator_is_told_each_models_thrusters(self):
        trajectories, vessel = straight_run()
        link, _ = run(trajectories, vessel)
        assert link.started[0] == {"os": thruster_constants(hull_dynamics(vessel, CALM))}
        assert link.started[0]["os"]["thrusters"] == ["port", "stbd"] and link.started[0]["os"]["helm"] is False

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


@pytest.mark.parametrize("steering", ["rudder", "vectored_thrust"])
class TestSteeringTypes:
    """A hull with a helm goes through the same loop: its autopilot's thrust and helm angle reach the actuator link."""

    def test_the_actuator_is_told_the_one_thruster_and_the_helm(self, steering):
        trajectories, vessel = steered_run(steering)
        link, _ = run(trajectories, vessel)
        model = link.started[0]["os"]
        assert (model["steering_type"], model["thrusters"], model["helm"]) == (steering, ["center"], True)

    def test_the_vessel_follows_its_reference(self, steering):
        trajectories, vessel = steered_run(steering)
        link, result = run(trajectories, vessel)
        states = [step[0] for step in result.states]
        assert max(abs(state.y) for state in states) < 1e-9, "the eastbound hull has nothing to turn it"
        assert states[-1].speed > 6.0 and states[-1].x > 100.0, "the hull has sped up from rest toward its reference"
        assert link.states["os"].helm_angle == 0.0, "the helm stays amidships on a straight course"

    def test_the_helm_steers_the_hull_onto_a_reference_to_port(self, steering):
        vessel = dataclasses.replace(scaled_vessel("30m"), _steering_type=steering)
        trajectories = TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene({vessel: ActorState(0.0, 0.0, 8.0, 0.5)}), 1, 30)
        dynamics = hull_dynamics(vessel, CALM)
        link = FakeHullLink({"os": (HullSurgeYawModel(dynamics), HullState(0.0, 0.0, 0.0, 8.0, 0.0, 0.0))})
        participants = {0: LosWaypointFollower(vessel, trajectories.state_list(vessel), trajectories.time_step)}
        autopilots = {0: TwinThrustAutopilot(AutopilotGains.from_dynamics(dynamics, vessel, 0.1))}
        helm_angles = []
        result = run_gz_lockstep(
            link, {0: "os"}, participants, autopilots, {0: vessel}, {0: thruster_constants(dynamics)}, 1.0, 30, 7, on_step=lambda index, states: helm_angles.append(link.states["os"].helm_angle)
        )
        assert result.states[-1][0].heading > 0.1, "the hull started heading east and has turned to port toward its reference"
        assert min(helm_angles) < -0.05, "a negative helm angle turns the vessel to port"
        if steering == "rudder":
            assert max(helm_angles[:10]) <= 0.0, "a rudder goes to port from the start (a vectored thruster that brakes first steers astern, helm the other way)"

    def test_the_same_inputs_give_the_same_digest(self, steering):
        trajectories, vessel = steered_run(steering)
        assert run(trajectories, vessel)[1].state_digest() == run(trajectories, vessel)[1].state_digest()

    def test_a_late_thrust_is_counted_once_per_step(self, steering):
        trajectories, vessel = steered_run(steering)
        assert run(trajectories, vessel, late_steps={3, 40})[1].late_commands == 2

    def test_run_gz_custom_records_the_steering_type(self, monkeypatch, steering):
        trajectories, vessel = steered_run(steering)
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", lambda host, port: setup_run(trajectories, vessel)[0])
        result = run_gz_custom(trajectories, gz_custom_instance(trajectories), steps=5)
        assert result.run_record["steering_types"] == {"0": steering}
        assert result.states[-1][0].x > 0.0


class TestHull:
    def test_thruster_constants_are_the_sdfs(self):
        _, vessel = straight_run()
        dynamics = hull_dynamics(vessel, CALM)
        assert thruster_constants(dynamics) == {
            "steering_type": "skid",
            "thrusters": ["port", "stbd"],
            "helm": False,
            "thrust_coefficient": sdf_value(dynamics.thrust_coefficient),
            "propeller_diameter": sdf_value(dynamics.propeller_diameter),
            "fluid_density": FLUID_DENSITY,
            "max_thrust": sdf_value(dynamics.max_thrust),
        }

    @pytest.mark.parametrize("steering", ["rudder", "vectored_thrust"])
    def test_a_hull_with_a_helm_has_one_thruster(self, steering):
        dynamics = hull_dynamics(steered_run(steering)[1], CALM)
        constants = thruster_constants(dynamics)
        assert (constants["steering_type"], constants["thrusters"], constants["helm"]) == (steering, ["center"], True)
        assert constants["max_thrust"] == sdf_value(dynamics.max_thrust)

    def test_a_vessel_model_preset_changes_the_hull(self):
        """The dynamics are those of the model generated with the preset, here the block coefficient of the Hanjin Pretoria."""
        _, vessel = panamax_run()
        assert hull_dynamics(vessel, CALM).hull.block_coefficient == pytest.approx(0.65)
        assert hull_dynamics(vessel, CALM, None).hull.block_coefficient == pytest.approx(0.65)
        preset = hull_dynamics(vessel, CALM, "hanjin_pretoria")
        assert preset.hull.block_coefficient == pytest.approx(0.817)
        assert preset.total_mass > hull_dynamics(vessel, CALM).total_mass

    def test_a_preset_the_vessel_cannot_take_is_an_error(self):
        _, vessel = straight_run()
        with pytest.raises(VesselOutOfPresetBounds):
            hull_dynamics(vessel, CALM, "hanjin_pretoria")
        with pytest.raises(UnknownVesselModelPreset):
            hull_dynamics(vessel, CALM, "titanic")


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
        assert record["steering_types"] == {"0": "skid"}
        assert "vessel_model_presets" not in record, "no vessel runs a preset"

    def test_run_gz_custom_derives_the_hull_with_the_vessels_model_preset(self, monkeypatch):
        """The autopilot's gains and the actuator's thruster constants come from the model generated with the preset."""
        trajectories, vessel = panamax_run()
        links, seen = [], []
        original = gz_lockstep_runner.hull_dynamics

        def recording_hull_dynamics(vessel, environment, preset_id=None):
            seen.append(preset_id)
            return original(vessel, environment, preset_id)

        def fake_link(host, port):
            initial = trajectories.initial_scene[vessel]
            links.append(FakeHullLink({"os": (HullSurgeYawModel(original(vessel, CALM, "hanjin_pretoria")), HullState(initial.x, initial.y, initial.heading, 0.0, 0.0, 0.0))}))
            return links[-1]

        monkeypatch.setattr(gz_lockstep_runner, "hull_dynamics", recording_hull_dynamics)
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", fake_link)
        instance = gz_custom_instance(trajectories)
        instance = dataclasses.replace(instance, vessels={"0": dataclasses.replace(instance.vessels["0"], vessel_model_preset="hanjin_pretoria")})
        result = run_gz_custom(trajectories, instance, steps=3)
        assert seen == ["hanjin_pretoria"]
        assert links[0].started[0]["os"] == thruster_constants(original(vessel, CALM, "hanjin_pretoria"))
        assert links[0].started[0]["os"] != thruster_constants(original(vessel, CALM)), "the fuller hull needs more thrust"
        assert result.run_record["vessel_model_presets"] == {"0": "hanjin_pretoria"}
        assert result.run_record["steering_types"] == {"0": "rudder"}

    def test_run_gz_custom_derives_the_automatic_model_without_a_preset(self, monkeypatch):
        trajectories, vessel = straight_run()
        seen = []
        original = gz_lockstep_runner.hull_dynamics

        def recording_hull_dynamics(vessel, environment, preset_id=None):
            seen.append(preset_id)
            return original(vessel, environment, preset_id)

        monkeypatch.setattr(gz_lockstep_runner, "hull_dynamics", recording_hull_dynamics)
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", lambda host, port: setup_run(trajectories, vessel)[0])
        run_gz_custom(trajectories, gz_custom_instance(trajectories), steps=3)
        assert seen == [None]

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
