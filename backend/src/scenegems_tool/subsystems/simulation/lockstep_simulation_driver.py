"""Drives an attended run whose vessels are all simulated with the registry's lockstep runners.

ArduAgent drives an instance with real vessels (arduagent_simulation_driver.py), because a
real vessel is reached over MQTT. An instance of simulated vessels only is run by the runner
its stacks resolve to, from the runner container of the attended simulation job
(cluster/worker_node/jobs/simulation_runners/attended_runner.py): every layer has its own
container in the job's stack, and the runner steps them (vessel_stack/hosting.py):

- kinematic: run_kinematic_instance against the kinematic simulator and each vessel's ASV
  system container (replay or USV Navigation);
- ardupilot on ardupilot_sim or gazebo: run_mavlink_stack against each vessel's ASV system
  container and SITL SERIAL0, as an attended run, so Mission Planner vessels are observed and
  left to their operator;
- custom on gazebo: run_gz_custom against each vessel's ASV system and controller containers
  and the gz-transport actuator in the Gazebo service.

Every step's states reach the caller as a scene. SITL paces itself to the instance's speedup;
the kinematic layer and a Gazebo world stepped by the runner would run as fast as the CPU
allows, so the driver holds them to the speedup on the wall clock, and the workbench shows
the run as it happens.
"""

import threading
import time
from typing import Any, Callable, Mapping, Optional

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack import hosting as stack_hosting
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.hosting import StackHosting
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

SceneObserver = Callable[[float, ConcreteScene], None]  # (scenario time in s, the scene at that time)


def uses_lockstep_driver(simulation: SimulationInstanceConfig) -> bool:
    """Whether the instance runs with a lockstep runner: every vessel is simulated."""
    return bool(simulation.vessels) and all(vessel.is_simulated for vessel in simulation.vessels.values())


class RunStopped(Exception):
    """Raised from a step observer to end a run that was asked to stop."""


class LockstepSimulationDriver:
    def __init__(
        self,
        simulation: SimulationInstanceConfig,
        trajectories: Trajectories,
        reference_geofence: Geofence,
        *,
        resolver: Optional[StackResolver] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        hosting: Optional[Callable[[], StackHosting]] = None,
    ):
        if not uses_lockstep_driver(simulation):
            raise ValueError("the lockstep driver runs instances whose vessels are all simulated; ArduAgent drives the others")
        self.simulation = simulation
        self.trajectories = trajectories
        self.reference_geofence = reference_geofence
        self.resolver = resolver or default_resolver()
        self._sleep = sleep
        self._clock = clock
        self._hosting_factory = hosting
        self._scene = trajectories.initial_scene
        self._lock = threading.Lock()

    @property
    def kind(self) -> str:
        """kinematic, mavlink or gz_custom: the runner the instance resolves to."""
        if self.simulation.simulation_layer == SimulationLayerId.KINEMATIC:
            return "kinematic"
        layers = {vessel.stack.control_layer for vessel in self.simulation.simulated_vessels.values()}
        return "gz_custom" if layers == {ControlLayerId.CUSTOM} else "mavlink"

    @property
    def current_scene(self) -> ConcreteScene:
        with self._lock:
            return self._scene

    def run(self, on_scene: SceneObserver, stop: threading.Event) -> Optional[Any]:
        """Run the instance until its trajectories' timespan, or until stop is set. Blocks.

        Returns the lockstep runner's result (its run record, steps and state digest), or None for a run that was stopped.
        """
        dt = float(self.trajectories.time_step)
        steps = int(round(self.trajectories.timespan / dt))
        paced = self.kind != "mavlink"
        started = self._clock()

        def observe(index: int, states: Mapping[int, ActorState]) -> None:
            if stop.is_set():
                raise RunStopped()
            if paced:
                wait = started + index * dt / max(self.simulation.speedup, 1) - self._clock()
                if wait > 0:
                    self._sleep(wait)
            scene = self._scene_of(states)
            with self._lock:
                self._scene = scene
            on_scene(index * dt, scene)

        try:
            if self.kind == "kinematic":
                return self._run_kinematic(dt, steps, observe)
            elif self.kind == "gz_custom":
                from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import run_gz_custom

                return run_gz_custom(self.trajectories, self.simulation, dt=dt, steps=steps, resolver=self.resolver, on_step=observe, hosting=self._hosting())
            else:
                from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import run_mavlink_stack

                return run_mavlink_stack(
                    self.trajectories,
                    self.simulation,
                    self.reference_geofence,
                    dt=dt,
                    steps=steps,
                    resolver=self.resolver,
                    attended=True,
                    on_step=lambda index, samples: observe(index, {vessel_id: sample.state for vessel_id, sample in samples.items()}),
                    hosting=self._hosting(),
                )
        except RunStopped:
            return None

    def _run_kinematic(self, dt: float, steps: int, observe: Callable[[int, Mapping[int, ActorState]], None]) -> Any:
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_instance

        actors = tuple(self.trajectories.initial_scene.actors)

        def on_step(index, snapshot) -> bool:
            observe(index, {actor.id: state for actor, state in zip(actors, snapshot) if isinstance(actor, ConcreteVessel)})
            return False

        return run_kinematic_instance(self.trajectories, self.simulation, dt=dt, steps=steps, hosting=self._hosting(), resolver=self.resolver, attended=True, on_step=on_step)

    def _hosting(self) -> StackHosting:
        """A hosting for one run: the containers of the job's stack, unless the driver was given another."""
        return (self._hosting_factory or stack_hosting.in_stack_hosting)()

    def _scene_of(self, states: Mapping[int, ActorState]) -> ConcreteScene:
        """The initial scene with every vessel at its observed state (static obstacles stay where they are)."""
        initial = self.trajectories.initial_scene
        return ConcreteScene({actor: states.get(actor.id, initial[actor]) for actor in initial.actors})
