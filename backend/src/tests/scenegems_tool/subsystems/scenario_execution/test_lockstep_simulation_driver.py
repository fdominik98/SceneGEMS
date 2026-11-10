"""LockstepSimulationDriver: the worker's runs of simulated vessels on the kinematic layer, over MAVLink and on the custom controller."""

import threading

import pytest

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.subsystems.scenario_execution.lockstep_simulation_driver import LockstepSimulationDriver, uses_lockstep_driver
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_runner
from tests.scenegems_tool.vessel_stack.control_layers.ardupilot.fake_sitl import FakeLink
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, stack_instance, straight_trajectories
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.test_gz_lockstep_runner import FakeHullLink


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def run(driver, stop=None):
    scenes = []
    driver.run(lambda clock, scene: scenes.append((clock, scene)), stop or threading.Event())
    return scenes


def kinematic(trajectories, speedup=1, asv_system=AsvSystemId.REPLAY):
    return stack_instance(SimulationLayerId.KINEMATIC, [vessel.id for vessel in trajectories.initial_scene.vessels], asv_system, ControlLayerId.NONE, speedup=speedup)


class TestChoice:
    def test_an_instance_of_simulated_vessels_runs_through_the_driver(self):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1])
        assert uses_lockstep_driver(instance)
        instance.vessels["1"].context = AgentContext.REAL
        assert not uses_lockstep_driver(instance), "a real vessel is reached only through ArduAgent"

    def test_a_real_vessel_is_refused(self):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1])
        instance.vessels["1"].context = AgentContext.REAL
        with pytest.raises(ValueError, match="all simulated"):
            LockstepSimulationDriver(instance, encounter_trajectories("head_on", 10), GEOFENCE)

    @pytest.mark.parametrize(
        "layer,control,kind",
        [
            (SimulationLayerId.KINEMATIC, ControlLayerId.NONE, "kinematic"),
            (SimulationLayerId.GAZEBO, ControlLayerId.ARDUPILOT, "mavlink"),
            (SimulationLayerId.GAZEBO, ControlLayerId.CUSTOM, "gz_custom"),
        ],
    )
    def test_the_runner_follows_the_stacks(self, layer, control, kind):
        driver = LockstepSimulationDriver(stack_instance(layer, [0, 1], control_layer=control), encounter_trajectories("head_on", 10), GEOFENCE)
        assert driver.kind == kind


class TestKinematic:
    def test_replay_reproduces_the_trajectories_one_scene_per_step(self):
        trajectories = encounter_trajectories("head_on", 20)
        time = FakeTime()
        scenes = run(LockstepSimulationDriver(kinematic(trajectories), trajectories, GEOFENCE, sleep=time.sleep, clock=time.clock))
        assert [clock for clock, _ in scenes] == [float(t) for t in range(21)]
        for t, (_, scene) in enumerate(scenes):
            for vessel in trajectories.initial_scene.vessels:
                assert scene[vessel] == trajectories.scene_list[t][vessel]

    def test_the_run_is_paced_to_the_speedup(self):
        trajectories = encounter_trajectories("head_on", 10)
        time = FakeTime()
        run(LockstepSimulationDriver(kinematic(trajectories, speedup=4), trajectories, GEOFENCE, sleep=time.sleep, clock=time.clock))
        assert time.now == pytest.approx(10 / 4)

    def test_usv_navigation_steers_its_vessel(self):
        trajectories = straight_trajectories(timespan=30)
        scenes = run(LockstepSimulationDriver(kinematic(trajectories, speedup=1000, asv_system=AsvSystemId.USV_NAVIGATION), trajectories, GEOFENCE))
        vessel = trajectories.initial_scene.vessels[0]
        assert scenes[-1][1][vessel].x > 100.0

    def test_a_stop_ends_the_run_and_the_driver_is_no_longer_running(self):
        trajectories = encounter_trajectories("head_on", 50)
        stop = threading.Event()
        driver = LockstepSimulationDriver(kinematic(trajectories, speedup=1000), trajectories, GEOFENCE)
        scenes = []

        def on_scene(clock, scene):
            scenes.append(clock)
            if clock == 3.0:
                stop.set()

        driver.run(on_scene, stop)
        assert scenes == [0.0, 1.0, 2.0, 3.0]
        assert not driver.is_running


class TestMavlink:
    @pytest.fixture
    def resolver(self):
        registry = build_registry()
        for adapter_id in ("replay_mavlink_lockstep", "usv_navigation_mavlink_lockstep"):
            registry.bind_runtime(adapter_id, lambda: FakeLink)
        return StackResolver(registry)

    @pytest.fixture(autouse=True)
    def fake_positions(self):
        FakeLink.start_positions = {0: (0.0, 0.0), 1: (6000.0, 0.0)}
        FakeLink.connections = []
        yield
        FakeLink.start_positions = {}
        FakeLink.connections = []

    def test_mission_planner_vessels_are_left_to_their_operator(self, resolver):
        trajectories = encounter_trajectories("head_on", 6)
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1])
        operated = instance.vessels["1"]
        operated.stack = type(operated.stack)(AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
        scenes = run(LockstepSimulationDriver(instance, trajectories, GEOFENCE, resolver=resolver))
        assert [clock for clock, _ in scenes] == [float(t) for t in range(7)]
        assert all(isinstance(actor, ConcreteVessel) for actor in scenes[-1][1].actors)
        assert not FakeLink.connections[1].armed


class TestGzCustom:
    def test_the_custom_controller_runs_on_the_actuator(self, monkeypatch):
        trajectories = straight_trajectories(timespan=5)
        vessel = trajectories.initial_scene.vessels[0]
        hull = (HullSurgeYawModel(gz_lockstep_runner.hull_dynamics(vessel, EnvironmentConfig.calm())), HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
        monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", lambda host, port: FakeHullLink({"agent_0": hull}))  # the model is named after the agent
        time = FakeTime()
        instance = stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.CUSTOM, speedup=2)
        scenes = run(LockstepSimulationDriver(instance, trajectories, GEOFENCE, sleep=time.sleep, clock=time.clock))
        assert [clock for clock, _ in scenes] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        assert time.now == pytest.approx(2.5), "paced to 2x"
