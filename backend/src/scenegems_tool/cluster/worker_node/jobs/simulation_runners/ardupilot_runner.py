"""The simulation job's ardupilot runner: replay or USV Navigation over the lockstep MAVLink adapters, on a SITL or Gazebo stack per job.

The payload's simulation_layer decides the layer: ardupilot_sim runs SITL's own physics, gazebo
SITL's JSON backend against a Gazebo world. Its mode decides the ASV software, as the kinematic
runner's does: replay puts every vessel on replay (replay_mavlink_lockstep), usv_navigation puts
the own ship (the scene's OS unless own_ship_id names another vessel) on USV Navigation
(usv_navigation_mavlink_lockstep, its heading and speed sent as GUIDED targets) and the others on
replay. The worker node resolves the instance, generates the vessel stack into the job's folder and adds
a runner from the scenario execution image on the stack network (vessel_job_stack.py). Every
vessel has its SITL and its ASV software container; the runner steps the ASV software, sends its
commands to the vessel's SITL SERIAL0 (mavlink_lockstep_runner.run_mavlink_stack) and returns the run.

Observed live, the runner forwards each step's observed states as frames, at most a bounded
number a second at the stack's own pace: SITL runs free at the payload's speedup, so the run is
not slowed to the observers' speed (that would delay its commands in SITL time and change it).

With monitor live, the COLREGS monitor judges every lockstep step in process (live_monitor.py),
whether or not the run is observed, and a judged step's frame carries its verdicts. The lockstep
runner does not stop early, so the monitor has no early stop here. A step's scene is the
vessels' observed states plus the static obstacles at their initial state, as in the run's
trajectories (include_trajectories).

The generated files reach SITL and Gazebo through the runtime assets volume, so the caller
must run where that volume is mounted at RUNTIME_ASSETS_FOLDER: the worker node daemon's container
or the workbench backend's.
"""

import threading
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Mapping, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import GeofencePayload, TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.worker_node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicMode, UsvNavigationPayload, check_closed_loop_options, own_ship
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import JobStack
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import STACK_NETWORK  # noqa: F401  (the network of every service of the job's stack)

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.vessel_stack.hosting import StackHosting

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (
    ArtifactField("states", ArtifactKind.TRAJECTORIES),  # the state log
    ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),
)


class ArduPilotSimulationLayer(str, Enum):
    ARDUPILOT_SIM = "ardupilot_sim"  # SITL's internal physics
    GAZEBO = "gazebo"  # SITL's JSON backend against a Gazebo world


def vessel_stacks(simulation_layer: ArduPilotSimulationLayer, mode: KinematicMode = KinematicMode.REPLAY) -> Tuple[StackTriple, ...]:
    """The vessel stacks a run on the layer runs: replay on ArduPilot for the vessels that replay, USV Navigation for the own ship in mode usv_navigation."""
    layer = SimulationLayerId(simulation_layer.value)
    replay = (AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, layer)
    if mode == KinematicMode.REPLAY:
        return (replay,)
    return (replay, (AsvSoftwareId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, layer))


class ArduPilotSimulationPayload(ProtocolModel):
    runner: Literal[SimulationRunner.ARDUPILOT]
    simulation_layer: ArduPilotSimulationLayer
    mode: KinematicMode = KinematicMode.REPLAY
    trajectories: TrajectoriesInput
    own_ship_id: Optional[int] = None  # usv_navigation only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only; from the own ship's trajectory when None
    geofence: GeofencePayload  # maps the local frame to SITL's home positions
    speedup: int = Field(default=1, ge=1)  # requested SITL pace
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None, 1 s when Rover cannot take that (lockstep_dt)
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0
    start_boot_s: Optional[float] = Field(default=None, ge=0.0)  # SITL time of scenario time 0; the next quantum when None
    include_states: bool = True  # return the observed state of every vessel at every step
    monitor: SimulationMonitor = SimulationMonitor.NONE
    colregs_constraints_content: Optional[str] = None  # live only: COLREGS constants YAML; the general maritime defaults when None
    include_trajectories: bool = False  # return the observed run as trajectories, as the kinematic runner does
    timeout_s: float = Field(default=1800.0, gt=0.0)

    @model_validator(mode="after")
    def _closed_loop_options_need_closed_loop(self) -> "ArduPilotSimulationPayload":
        check_closed_loop_options(self.mode, self.own_ship_id, self.usv_navigation)
        return self

    @model_validator(mode="after")
    def _monitor_options_need_the_live_monitor(self) -> "ArduPilotSimulationPayload":
        if self.monitor != SimulationMonitor.LIVE and self.colregs_constraints_content is not None:
            raise ValueError("colregs_constraints_content applies only to monitor live")
        if (self.monitor == SimulationMonitor.LIVE or self.include_trajectories) and self.dt is not None and not float(self.dt).is_integer():
            raise ValueError("the live monitor and the trajectories need a whole number of seconds as dt")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        return vessel_stacks(self.simulation_layer, self.mode)


PAYLOAD_MODEL = ArduPilotSimulationPayload


def _instance(payload: ArduPilotSimulationPayload):
    """The trajectories, the instance and the own ship's USV Navigation parameters (by vessel id, empty in replay); ValueError when own_ship_id names no vessel."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import mavlink_instance

    trajectories = to_trajectories(payload.trajectories)
    asv_software: Dict[int, AsvSoftwareId] = {}
    parameters = {}
    if payload.mode == KinematicMode.USV_NAVIGATION:
        own = own_ship(trajectories.initial_scene, payload.own_ship_id)
        asv_software[own.id] = AsvSoftwareId.USV_NAVIGATION
        if payload.usv_navigation is not None:
            parameters[own.id] = payload.usv_navigation.to_parameters()
    instance = mavlink_instance(trajectories, SimulationLayerId(payload.simulation_layer.value), asv_software, environment=EnvironmentConfig.calm(seed=payload.seed), speedup=payload.speedup)
    return trajectories, instance, parameters


def build_job_stack(job: JobSpec, worker_node: WorkerNodeContext, payload: ArduPilotSimulationPayload) -> JobStack:
    """The job's stack: SITL and an ASV software container per vessel, Gazebo on the gazebo layer, and the runner."""
    try:
        trajectories, instance, _ = _instance(payload)
    except ValueError as error:
        raise JobFailed(f"Simulation payload rejected: {error}", retryable=False) from error
    return build_vessel_job_stack(job, worker_node, instance, trajectories, payload.geofence.to_geofence())


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, payload: ArduPilotSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    report.status(f"generating the {payload.simulation_layer.value} stack")
    stack = build_job_stack(job, worker_node, payload)
    # SITL runs free at the payload's speedup, so an observed run is not slowed down and keeps its timeout
    return stack.run(job_document(job), report, timeout_s=payload.timeout_s, cancel=cancel, observation=worker_node.observations.of(job), paced=False)


def sample_state(sample: Any) -> Any:
    """The state of a lockstep MAVLink sample (StampedState)."""
    return sample.state


def step_scene(initial_scene, state_of: Callable[[Any], Any] = sample_state) -> Callable[[Mapping[int, Any]], Dict[Any, Any]]:
    """A lockstep step's scene as {actor: state}: each vessel's observed state, the static obstacles where the scene put them.

    state_of reads a vessel's state from what the lockstep runner observed: a StampedState's
    state by default, the state itself for a runner that observes plain ActorStates (the Gazebo runner).
    """
    vessels = {vessel.id: vessel for vessel in initial_scene.vessels}
    obstacles = {obstacle: initial_scene[obstacle] for obstacle in initial_scene.obstacles}

    def build(samples: Mapping[int, Any]) -> Dict[Any, Any]:
        return {**{vessels[vessel_id]: state_of(sample) for vessel_id, sample in samples.items()}, **obstacles}

    return build


def frame_builder(
    scenario_id: str, trajectories, dt: float, monitor: Optional[LiveMonitor] = None, state_of: Callable[[Any], Any] = sample_state
) -> Callable[[int, Mapping[int, Any]], Dict[str, Any]]:
    """A lockstep step's frame in the workbench's wire format: the monitored scene when the live monitor judged the step, else the scene alone."""
    from concrete_level.trajectory_generation.scene_builder import SceneBuilder
    from scenegems_tool.gateway.serialization import serialize_frame, serialize_monitored_frame

    scene_of = step_scene(trajectories.initial_scene, state_of)
    time_step = int(dt) if float(dt).is_integer() else dt

    def build(index: int, samples: Mapping[int, Any]) -> Dict[str, Any]:
        timestamp = index * time_step
        if monitor is not None and monitor.last_monitored_index == index:
            return serialize_monitored_frame(scenario_id=scenario_id, monitored_scene=monitor.last_monitored, timestamp=timestamp, time_step=time_step)
        builder = SceneBuilder()
        builder.set_states_as_dict(scene_of(samples))
        return serialize_frame(scenario_id=scenario_id, scene=builder.build(), timestamp=timestamp, time_step=time_step)

    return build


def step_observer(trajectories, monitor: Optional[LiveMonitor], observer, state_of: Callable[[Any], Any] = sample_state) -> Optional[Callable[[int, Mapping[int, Any]], None]]:
    """The lockstep step observer: the live monitor's, the observation's after it, both or none."""
    if monitor is None and observer is None:
        return None
    scene_of = step_scene(trajectories.initial_scene, state_of)

    def on_step(index: int, samples: Mapping[int, Any]) -> None:
        if monitor is not None:
            scene = scene_of(samples)
            monitor.on_step(index, [scene[actor] for actor in monitor.actors])
        if observer is not None:
            observer.step(index, samples)

    return on_step


def observed_trajectories(trajectories, result, dt: float, state_of: Callable[[Any], Any] = sample_state):
    """The run as trajectories: every step's observed vessel states and the static obstacles."""
    from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder

    scene_of = step_scene(trajectories.initial_scene, state_of)
    builder = TrajectoryBuilder(time_step=int(dt))
    for step_states in result.states:
        builder.add_scene_as_dict(scene_of(dict(zip(result.vessel_ids, step_states))))
    return builder.build()


def execute(job: JobSpec, payload: ArduPilotSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part: step every vessel's ASV software container, drive its SITL in lockstep and describe the run; observation forwards its states live.

    hosting is where the ASV software runs: the stack's containers unless given (vessel_stack/hosting.py).
    """
    from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import lockstep_dt, run_mavlink_stack
    from scenegems_tool.vessel_stack.hosting import in_stack_hosting

    trajectories, instance, parameters = _instance(payload)
    dt = lockstep_dt(trajectories.time_step) if payload.dt is None else payload.dt
    steps = payload.steps if payload.steps is not None else int(round(trajectories.timespan / dt))
    monitor = LiveMonitor(trajectories.initial_scene.actors, int(dt), payload.colregs_constraints_content, early_stop=False) if payload.monitor == SimulationMonitor.LIVE else None
    observer = None
    if observation is not None:
        observer = observation.observer(frame_builder(job.job_id, trajectories, dt, monitor), dt, last_index=steps, pace=False, stride_speed=float(payload.speedup))
    on_step = step_observer(trajectories, monitor, observer)
    status(f"connecting to SITL for the {payload.mode.value} run" + (" with the live monitor" if monitor is not None else ""))
    result = run_mavlink_stack(
        trajectories,
        instance,
        payload.geofence.to_geofence(),
        dt=payload.dt,
        steps=payload.steps,
        start_boot_s=payload.start_boot_s,
        on_step=on_step,
        usv_navigation_parameters=parameters or None,
        hosting=hosting or in_stack_hosting(),
    )
    status("run finished", 1.0)
    data: JobResultData = {
        "run_record": dict(result.run_record),
        "steps": result.steps,
        "achieved_speedup": result.achieved_speedup,
        "state_digest": result.state_digest(),
    }
    if payload.include_states:
        # Per vessel id: one [sitl_ms, x, y, speed, heading] row per step from scenario time 0.
        data["states"] = {
            str(vessel_id): [[sample.boot_ms, sample.state.x, sample.state.y, sample.state.speed, sample.state.heading] for sample in column]
            for vessel_id, column in zip(result.vessel_ids, zip(*result.states))
        }
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=False)
    if payload.include_trajectories:
        data["trajectories"] = observed_trajectories(trajectories, result, dt).to_dict()
    return data
