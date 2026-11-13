"""MOOS-IvP in the lockstep runners: its parameters, its place in every stack it can drive, and a kinematic run with it.

The helm of these runs is the tests' own (fake_helm.py) behind the real server and wire protocol; the real helm is
tested in its image (test_moos_ivp_image.py).
"""

import math
from pathlib import Path

import pytest

from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import RunParameters
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_specs import MOOS_IVP_CONTAINER, MOOS_IVP_LAYER
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import mavlink_instance
from scenegems_tool.vessel_stack.registry.catalog import default_registry, default_resolver
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import gz_custom_instance
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import kinematic_instance, run_kinematic_closed_loop, run_kinematic_instance
from tests.scenegems_tool.vessel_stack.asv_system.moos_ivp.fake_helm import FakeHelm
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_hosting
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

REPO_ROOT = Path(__file__).resolve().parents[7]


@pytest.fixture(scope="module")
def head_on():
    return encounter_trajectories("head_on", 300)


class TestRunParameters:
    def test_software_without_parameters_has_none(self, head_on):
        parameters = RunParameters()
        own = head_on.initial_scene.os
        assert parameters.resolve(AsvSystemId.REPLAY, own, head_on, 1.0) is None
        assert parameters.resolve(AsvSystemId.MISSION_PLANNER, own, head_on, 1.0) is None, "no lockstep runner steps it, so it has no runtime to ask"
        assert parameters.by_vessel == {} and parameters.record() == {}

    def test_each_software_gets_its_own_defaults(self, head_on):
        parameters = RunParameters()
        own, target = head_on.initial_scene.vessels
        assert isinstance(parameters.resolve(AsvSystemId.MOOS_IVP, own, head_on, 1.0), MoosIvpParameters)
        assert isinstance(parameters.resolve(AsvSystemId.USV_NAVIGATION, target, head_on, 1.0), UsvNavigationParameters)
        assert set(parameters.by_vessel) == {0, 1}
        record = parameters.record()
        assert list(record) == ["moos_ivp", "usv_navigation"] and list(record["moos_ivp"]) == ["0"] and list(record["usv_navigation"]) == ["1"]
        assert record["moos_ivp"]["0"] == parameters.by_vessel[0].as_dict()

    def test_the_callers_parameters_are_taken_for_the_software_they_were_given_for(self, head_on):
        own = head_on.initial_scene.os
        chosen = MoosIvpParameters.from_reference(own, head_on.state_list(own), head_on.initial_scene.actors, 15.0)
        parameters = RunParameters({AsvSystemId.MOOS_IVP: {0: chosen}, AsvSystemId.USV_NAVIGATION: None})
        assert parameters.resolve(AsvSystemId.MOOS_IVP, own, head_on, 1.0) is chosen
        assert isinstance(RunParameters({AsvSystemId.MOOS_IVP: {0: chosen}}).resolve(AsvSystemId.USV_NAVIGATION, own, head_on, 1.0), UsvNavigationParameters)


class TestStacks:
    def test_the_layer_brings_the_image_and_every_adapter_the_same_container(self):
        registry = default_registry()
        assert MOOS_IVP_LAYER.containers == (MOOS_IVP_CONTAINER,)
        assert MOOS_IVP_CONTAINER.default_image == "scenegems-moos-ivp:latest"
        contributors = {registry.docker(spec_id) for spec_id in ("moos_ivp_heading_speed", "moos_ivp_custom_controller_input", "moos_ivp_mavlink_lockstep")}
        assert len(contributors) == 1 and None not in contributors

    def test_the_build_script_stamps_the_image_with_what_the_container_spec_names(self):
        build_script = (REPO_ROOT / "deploy" / "scripts" / "build.sh").read_text(encoding="utf-8")
        step = build_script[build_script.index('"scenegems-moos-ivp:latest"') :].split("}")[0]
        for source in MOOS_IVP_CONTAINER.build_fingerprint_sources:
            if source != MOOS_IVP_CONTAINER.upstream_pins_file:  # the build helpers add the pins file to every image whose Dockerfile declares a pin
                assert f'"$SCRIPT_DIR/{source}"' in step, source
        dockerfile = (REPO_ROOT / "deploy" / "images" / "moos_ivp" / "Dockerfile").read_text(encoding="utf-8")
        pins = (REPO_ROOT / "deploy" / "images" / "upstream_pins.env").read_text(encoding="utf-8")
        for pin in ("UBUNTU_BASE_IMAGE", "MOOS_IVP_REPO", "MOOS_IVP_COMMIT"):
            assert f"ARG {pin}\n" in dockerfile and f"\n{pin}=" in pins, pin

    def test_on_ardupilot_it_runs_through_its_lockstep_mavlink_adapter(self, head_on):
        instance = mavlink_instance(head_on, SimulationLayerId.ARDUPILOT_SIM, {0: AsvSystemId.MOOS_IVP})
        assert instance.vessels["0"].adapter_ids == ("moos_ivp_mavlink_lockstep",) and instance.vessels["1"].adapter_ids == ("replay_mavlink_lockstep",)
        assert default_resolver().require_instance(instance, attended=False).chains["0"].asv_adapter.id == "moos_ivp_mavlink_lockstep"

    def test_on_the_custom_controller_it_sets_the_heading_and_speed(self, head_on):
        instance = gz_custom_instance(head_on, {0: AsvSystemId.MOOS_IVP})
        chain = default_resolver().require_instance(instance, attended=False).chains["0"]
        assert chain.stack.control_layer == ControlLayerId.CUSTOM and chain.asv_adapter.id == "moos_ivp_custom_controller_input"


class TestKinematicRun:
    def test_the_own_ship_on_moos_ivp_against_a_replaying_target(self, head_on):
        FakeHelm.started.clear()
        instance = kinematic_instance(head_on, {0: AsvSystemId.MOOS_IVP})
        with loopback_hosting(instance) as hosting:
            run = run_kinematic_instance(head_on, instance, hosting=hosting)
        (helm,) = FakeHelm.started
        assert run.result.steps == 300 and len(helm.passes) == 300, "one helm pass per step"
        assert run.stacks == {"0": "moos_ivp, none, kinematic", "1": "replay, none, kinematic"}
        assert "moos_ivp_heading_speed" in run.spec_ids
        assert isinstance(run.parameters[0], MoosIvpParameters) and set(run.parameters) == {0}
        assert run.reports[0]["events"] == [[0.0, "spawn", "avd_c1"]] and run.reports[0]["no_decision_steps"] == 0
        own_track = [states[0] for states in run.result.states]
        assert min(state.y for state in own_track) < -100.0 and max(state.y for state in own_track) <= 0.0, "the fake helm turns to starboard of an eastward course, which is south"
        assert all(math.isfinite(state.x) for state in own_track)

    def test_the_run_repeats_bit_for_bit(self, head_on):
        instance = kinematic_instance(head_on, {0: AsvSystemId.MOOS_IVP})
        digests = []
        for _ in range(2):
            with loopback_hosting(instance) as hosting:
                digests.append(run_kinematic_instance(head_on, instance, hosting=hosting).result.state_digest())
        assert digests[0] == digests[1]

    def test_the_callers_parameters_reach_the_helm(self, head_on):
        FakeHelm.started.clear()
        own = head_on.initial_scene.os
        defaults = MoosIvpParameters.from_reference(own, head_on.state_list(own), head_on.initial_scene.actors, 1.0)
        chosen = MoosIvpParameters(**{**defaults.__dict__, "goal": (1234.0, 500.0), "avoidance": "cpa"})
        instance = kinematic_instance(head_on, {0: AsvSystemId.MOOS_IVP})
        with loopback_hosting(instance) as hosting:
            run = run_kinematic_instance(head_on, instance, steps=3, moos_ivp_parameters={0: chosen}, hosting=hosting)
        (helm,) = FakeHelm.started
        assert "point = 1234.0000,500.0000" in helm.behaviours and "Behavior = BHV_AvoidCollision" in helm.behaviours
        assert run.parameters[0] is chosen

    def test_without_containers_the_run_says_where_moos_ivp_runs(self, head_on):
        with pytest.raises(RuntimeError, match="MOOS-IvP runs only in its container"):
            run_kinematic_instance(head_on, kinematic_instance(head_on, {0: AsvSystemId.MOOS_IVP}))


class TestClosedLoop:
    """run_kinematic_closed_loop with MOOS-IvP on the own ship: what the simulation job's kinematic runner runs in mode moos_ivp."""

    def test_the_run_record_has_the_helms_block(self, head_on):
        FakeHelm.started.clear()
        instance = kinematic_instance(head_on, {0: AsvSystemId.MOOS_IVP})
        with loopback_hosting(instance) as hosting:
            result = run_kinematic_closed_loop(head_on, asv_system=AsvSystemId.MOOS_IVP, steps=40, hosting=hosting)
        record = result.run_record
        assert record["stacks"] == {"0": "moos_ivp, none, kinematic", "1": "replay, none, kinematic"} and record["steps"] == 40
        assert "usv_navigation" not in record
        block = record["moos_ivp"]
        assert (
            block["vessel"] == 0
            and block["parameters"] == MoosIvpParameters.from_reference(head_on.initial_scene.os, head_on.state_list(head_on.initial_scene.os), head_on.initial_scene.actors, 1.0).as_dict()
        )
        assert block["avoidance_behaviour"] == "BHV_AvdColregsV22" and block["events"] == [[0.0, "spawn", "avd_c1"]] and block["goal_reached_at"] is None and block["no_decision_steps"] == 0

    def test_the_named_vessel_and_the_callers_parameters(self, head_on):
        FakeHelm.started.clear()
        target = head_on.initial_scene.vessels[1]
        defaults = MoosIvpParameters.from_reference(target, head_on.state_list(target), head_on.initial_scene.actors, 1.0)
        chosen = MoosIvpParameters(**{**defaults.__dict__, "avoidance": "cpa"})
        with loopback_hosting(kinematic_instance(head_on, {1: AsvSystemId.MOOS_IVP})) as hosting:
            record = run_kinematic_closed_loop(head_on, own_ship_id=1, asv_system=AsvSystemId.MOOS_IVP, moos_ivp_parameters=chosen, steps=5, hosting=hosting).run_record
        assert record["moos_ivp"]["vessel"] == 1 and record["moos_ivp"]["parameters"]["avoidance"] == "cpa"
        assert record["stacks"] == {"0": "replay, none, kinematic", "1": "moos_ivp, none, kinematic"}

    def test_only_software_that_decides_heading_and_speed_closes_the_loop(self, head_on):
        with pytest.raises(ValueError, match="the closed loop runs USV Navigation or MOOS-IvP on the own ship, not replay"):
            run_kinematic_closed_loop(head_on, asv_system=AsvSystemId.REPLAY)
