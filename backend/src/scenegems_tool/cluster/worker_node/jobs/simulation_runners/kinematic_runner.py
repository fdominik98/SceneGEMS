"""The simulation job's kinematic runner: a lockstep run on the kinematic layer, on a stack per job.

Three modes: replay of every vessel's generated trajectory (kinematic_runner.run_kinematic_replay),
or an ASV system on the own ship against replaying targets (run_kinematic_closed_loop): USV Navigation
in mode usv_navigation, MOOS-IvP's helm in mode moos_ivp.
The stack holds the kinematic simulator, one container for the scenario, and an ASV system
container per vessel (vessel_job_stack.py); the runner, from the simulation subsystem image, owns
the clock and carries the commands and states between them. The stack's network is its own and
reaches nothing else. A run is bit-identical for the same payload, and the result carries its
state digest.

With monitor live, the worker node's monitoring subsystem judges the run's scenes as one series
(live_monitor.py), with the post-hoc monitor's summary (subsystems/monitoring/rule_outcomes.py), and
early_stop ends the run once every rule is decided: the run then waits for each step's answer, so it
stops at the same step every time. A run without a monitor is the same run as before the monitor existed.

Observed live (the worker node's observation, in_container/run_observation.py), the run is paced to
the observers' speed and writes frames: every vessel's state at the step and, with the live
monitor, its outcomes. The step observer only reads the states, so the digest and the result
do not depend on whether or when the run was observed.
"""

import dataclasses
import threading
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Mapping, Optional, Tuple

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.worker_node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import JobStack
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import parameters_for as moos_ivp_parameters_for
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import DEFAULT_PRESCRIBED_TIME_S, UsvNavigationParameters
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.vessel_stack.hosting import StackHosting

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)


class KinematicMode(str, Enum):
    REPLAY = "replay"  # every vessel replays its trajectory
    USV_NAVIGATION = "usv_navigation"  # the own ship runs USV Navigation, the others replay
    MOOS_IVP = "moos_ivp"  # the own ship runs MOOS-IvP's helm, the others replay


# The ASV system the own ship runs in each mode but replay, in which every vessel replays
OWN_SHIP_ASV_SYSTEMS: Dict[KinematicMode, AsvSystemId] = {KinematicMode.USV_NAVIGATION: AsvSystemId.USV_NAVIGATION, KinematicMode.MOOS_IVP: AsvSystemId.MOOS_IVP}


def mode_stacks(mode: KinematicMode, control_layer: ControlLayerId, simulation_layer: SimulationLayerId) -> Tuple[StackTriple, ...]:
    """The vessel stacks a run of the mode runs on these layers: replay for the vessels that replay, and the mode's ASV system for the own ship (every runner with the modes uses it)."""
    replay = (AsvSystemId.REPLAY, control_layer, simulation_layer)
    own_ship_asv_system = OWN_SHIP_ASV_SYSTEMS.get(mode)
    return (replay,) if own_ship_asv_system is None else (replay, (own_ship_asv_system, control_layer, simulation_layer))


def vessel_stacks(mode: KinematicMode) -> Tuple[StackTriple, ...]:
    """The vessel stacks a run of the mode runs: replay for the vessels that replay, USV Navigation or MOOS-IvP for the own ship in its mode."""
    return mode_stacks(mode, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)


class UsvNavigationPayload(ProtocolModel):
    """UsvNavigationParameters in full; leave it out for the SceneGEMS defaults (from_reference).

    horizon is left out of the JSON while it is absent, so a config written before it existed
    keeps its JSON and its hash.
    """

    goal: Tuple[float, float]
    speed: float = Field(gt=0.0)
    safety_radius: float = Field(gt=0.0)
    control_horizon: float = Field(gt=0.0)
    prescribed_time: float = Field(default=DEFAULT_PRESCRIBED_TIME_S, gt=0.0)
    horizon: Optional[float] = Field(default=None, gt=0.0)
    runtime_options: Dict[str, float] = Field(default_factory=dict)

    @model_serializer(mode="wrap")
    def _without_absent_horizon(self, handler: SerializerFunctionWrapHandler) -> Dict[str, Any]:
        data = handler(self)
        if self.horizon is None:
            data.pop("horizon", None)
        return data

    def to_parameters(self) -> UsvNavigationParameters:
        return UsvNavigationParameters(
            goal=self.goal,
            speed=self.speed,
            safety_radius=self.safety_radius,
            control_horizon=self.control_horizon,
            prescribed_time=self.prescribed_time,
            horizon=self.horizon,
            runtime_options=tuple(sorted(self.runtime_options.items())),
        )


class MoosIvpPayload(ProtocolModel):
    """Values of MoosIvpParameters that replace the SceneGEMS defaults of a scene (MoosIvpParameters.from_reference).

    Every field is optional: one that is left out keeps the value derived from the scene, so a payload
    may name the avoidance behaviour alone. Absent fields are left out of the JSON.
    """

    goal: Optional[Tuple[float, float]] = None
    speed: Optional[float] = Field(default=None, gt=0.0)
    max_speed: Optional[float] = Field(default=None, gt=0.0)
    avoidance: Optional[Literal["colregs", "cpa"]] = None  # moos_ivp_parameters.AVOIDANCE_BEHAVIOURS
    min_util_cpa_dist: Optional[float] = Field(default=None, ge=0.0)
    max_util_cpa_dist: Optional[float] = Field(default=None, ge=0.0)
    pwt_outer_dist: Optional[float] = Field(default=None, gt=0.0)
    pwt_inner_dist: Optional[float] = Field(default=None, gt=0.0)
    completed_dist: Optional[float] = Field(default=None, gt=0.0)
    capture_radius: Optional[float] = Field(default=None, gt=0.0)
    behaviour_options: Optional[Dict[str, str]] = None  # further parameter lines of the avoidance behaviour, by name

    @model_validator(mode="after")
    def _given_values_agree(self) -> "MoosIvpPayload":
        """The order MoosIvpParameters asks for, among the values that are given; the rest is checked against each scene's own values when the run starts."""
        for smaller, larger in (
            ("speed", "max_speed"),
            ("min_util_cpa_dist", "max_util_cpa_dist"),
            ("pwt_inner_dist", "pwt_outer_dist"),
            ("pwt_outer_dist", "completed_dist"),
            ("pwt_inner_dist", "completed_dist"),
        ):
            low, high = getattr(self, smaller), getattr(self, larger)
            if low is not None and high is not None and low > high:
                raise ValueError(f"{smaller} must not exceed {larger}")
        return self

    @model_serializer(mode="wrap")
    def _without_absent_fields(self, handler: SerializerFunctionWrapHandler) -> Dict[str, Any]:
        return {name: value for name, value in handler(self).items() if value is not None}

    def apply(self, defaults: MoosIvpParameters) -> MoosIvpParameters:
        """The scene's defaults with this payload's values in their place; ValueError when the result contradicts itself."""
        given = {name: getattr(self, name) for name in type(self).model_fields if getattr(self, name) is not None}
        if "behaviour_options" in given:
            given["behaviour_options"] = tuple(sorted(given["behaviour_options"].items()))
        return dataclasses.replace(defaults, **given)


def check_closed_loop_options(mode: KinematicMode, own_ship_id: Optional[int], usv_navigation: Optional[UsvNavigationPayload], moos_ivp: Optional[MoosIvpPayload] = None) -> None:
    """own_ship_id applies to the modes with an ASV system on the own ship, and each software's parameters to its own mode (every runner with the modes checks it)."""
    if mode == KinematicMode.REPLAY and own_ship_id is not None:
        raise ValueError("own_ship_id applies only to the modes usv_navigation and moos_ivp")
    if usv_navigation is not None and mode != KinematicMode.USV_NAVIGATION:
        raise ValueError("usv_navigation parameters apply only to mode usv_navigation")
    if moos_ivp is not None and mode != KinematicMode.MOOS_IVP:
        raise ValueError("moos_ivp parameters apply only to mode moos_ivp")


def own_ship(scene, own_ship_id: Optional[int]):
    """The vessel that runs the mode's ASV system: the scene's own ship, or the vessel own_ship_id names; ValueError when the scene has none by that id."""
    own = scene.os if own_ship_id is None else next((vessel for vessel in scene.vessels if vessel.id == own_ship_id), None)
    if own is None:
        raise ValueError(f"No vessel with id {own_ship_id} in the scene")
    return own


def own_ship_asv_system(payload: Any, scene) -> Dict[int, AsvSystemId]:
    """The ASV system of the own ship by its vessel id, for a payload with the modes; empty in mode replay. ValueError when own_ship_id names no vessel."""
    asv_system = OWN_SHIP_ASV_SYSTEMS.get(payload.mode)
    return {} if asv_system is None else {own_ship(scene, payload.own_ship_id).id: asv_system}


def own_ship_parameters(payload: Any, trajectories, dt: float) -> Dict[AsvSystemId, Mapping[int, Any]]:
    """The parameters a payload with the modes gives for the own ship's ASV system, by ASV system and vessel id; empty when it gives none.

    USV Navigation's are given in full. MOOS-IvP's replace the scene's defaults value by value, so they are
    applied to the defaults of this run's trajectories and step here.
    """
    scene = trajectories.initial_scene
    if payload.mode == KinematicMode.USV_NAVIGATION and payload.usv_navigation is not None:
        return {AsvSystemId.USV_NAVIGATION: {own_ship(scene, payload.own_ship_id).id: payload.usv_navigation.to_parameters()}}
    if payload.mode == KinematicMode.MOOS_IVP and payload.moos_ivp is not None:
        own = own_ship(scene, payload.own_ship_id)
        return {AsvSystemId.MOOS_IVP: {own.id: payload.moos_ivp.apply(moos_ivp_parameters_for(own, trajectories, dt))}}
    return {}


class KinematicSimulationPayload(ProtocolModel):
    runner: Literal[SimulationRunner.KINEMATIC]
    mode: KinematicMode = KinematicMode.REPLAY
    trajectories: TrajectoriesInput
    own_ship_id: Optional[int] = None  # usv_navigation and moos_ivp only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only
    moos_ivp: Optional[MoosIvpPayload] = None  # moos_ivp only; left out of the JSON while absent
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0  # run seed (EnvironmentConfig.seed)
    monitor: SimulationMonitor = SimulationMonitor.NONE
    early_stop: bool = False  # live only: end the run once every rule of every relation is decided
    colregs_constraints_content: Optional[str] = None  # live only: COLREGS constants YAML; the general maritime defaults when None
    include_trajectories: bool = True  # return the simulated trajectories, not only the run record
    timeout_s: float = Field(default=600.0, gt=0.0)

    @model_validator(mode="after")
    def _closed_loop_options_need_closed_loop(self) -> "KinematicSimulationPayload":
        check_closed_loop_options(self.mode, self.own_ship_id, self.usv_navigation, self.moos_ivp)
        return self

    @model_serializer(mode="wrap")
    def _without_absent_moos_ivp(self, handler: SerializerFunctionWrapHandler) -> Dict[str, Any]:
        return without_absent_moos_ivp(self, handler)

    @model_validator(mode="after")
    def _monitor_options_need_the_live_monitor(self) -> "KinematicSimulationPayload":
        if self.monitor != SimulationMonitor.LIVE and (self.early_stop or self.colregs_constraints_content is not None):
            raise ValueError("early_stop and colregs_constraints_content apply only to monitor live")
        if self.monitor == SimulationMonitor.LIVE and self.dt is not None and not float(self.dt).is_integer():
            raise ValueError("the live monitor needs a whole number of seconds as dt")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        return vessel_stacks(self.mode)


def without_absent_moos_ivp(payload: Any, handler: SerializerFunctionWrapHandler) -> Dict[str, Any]:
    """A payload's JSON without moos_ivp while it is absent, so a payload written before the mode existed keeps its JSON."""
    data = handler(payload)
    if payload.moos_ivp is None:
        data.pop("moos_ivp", None)
    return data


PAYLOAD_MODEL = KinematicSimulationPayload


def kinematic_run_instance(payload: KinematicSimulationPayload):
    """The trajectories and the instance of the payload's run; ValueError when own_ship_id names no vessel."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import kinematic_instance

    trajectories = to_trajectories(payload.trajectories)
    return trajectories, kinematic_instance(trajectories, own_ship_asv_system(payload, trajectories.initial_scene), environment=EnvironmentConfig.calm(seed=payload.seed))


def build_job_stack(job: JobSpec, worker_node: WorkerNodeContext, payload: KinematicSimulationPayload) -> JobStack:
    """The job's stack: the kinematic simulator, an ASV system container per vessel, and the runner."""
    try:
        trajectories, instance = kinematic_run_instance(payload)
        own_ship_parameters(payload, trajectories, float(trajectories.time_step) if payload.dt is None else payload.dt)  # refused here, before the stack starts
    except ValueError as error:
        raise JobFailed(f"Simulation payload rejected: {error}", retryable=False) from error
    return build_vessel_job_stack(job, worker_node, instance, trajectories, worker_node.reference_geofence, monitored=payload.monitor == SimulationMonitor.LIVE)


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, payload: KinematicSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    report.status("generating the kinematic stack")
    stack = build_job_stack(job, worker_node, payload)
    # The runner steps the simulator, so an observed run is paced to the observers' speed and that time does not count against the timeout
    return stack.run(job_document(job), report, timeout_s=payload.timeout_s, cancel=cancel, observation=worker_node.observations.of(job), paced=True)


def frame_builder(scenario_id: str, actors, dt: float, monitor: Optional[LiveMonitor]) -> Callable[[int, Any], Dict[str, Any]]:
    """A step's frame in the workbench's wire format: the monitored scene when the live monitor judged the step, else the scene alone."""
    from concrete_level.trajectory_generation.scene_builder import SceneBuilder
    from scenegems_tool.gateway.serialization import serialize_frame

    actors = tuple(actors)
    time_step = int(dt) if float(dt).is_integer() else dt

    def build(index: int, states) -> Dict[str, Any]:
        timestamp = index * time_step
        judged = monitor.frame_of(index) if monitor is not None else None
        if judged is not None:
            return judged
        builder = SceneBuilder()
        builder.set_states_as_dict(dict(zip(actors, states)))
        return serialize_frame(scenario_id=scenario_id, scene=builder.build(), timestamp=timestamp, time_step=time_step)

    return build


def step_observer(monitor: Optional[LiveMonitor], observer) -> Optional[Callable[[int, Any], bool]]:
    """The run's step observer: the live monitor's (which may end the run), the observation's after it, both or none."""
    if observer is None:
        return monitor.on_step if monitor is not None else None

    def on_step(index: int, states) -> bool:
        stop = monitor.on_step(index, states) if monitor is not None else False
        observer.step(index, states, last=stop)
        return stop

    return on_step


def execute(job: JobSpec, payload: KinematicSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part: step the simulator and every vessel's ASV system container and describe the run; observation makes it observable live.

    hosting is where the simulator and the ASV system run: the stack's containers unless given (vessel_stack/hosting.py).
    """
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.hosting import in_stack_hosting
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay

    hosting = hosting or in_stack_hosting()
    trajectories = to_trajectories(payload.trajectories)
    environment = EnvironmentConfig.calm(seed=payload.seed)
    dt = float(trajectories.time_step) if payload.dt is None else payload.dt
    planned_steps = payload.steps if payload.steps is not None else int(round(trajectories.timespan / dt))
    monitor = LiveMonitor(trajectories.initial_scene.actors, int(dt), payload.colregs_constraints_content, payload.early_stop, job=job) if payload.monitor == SimulationMonitor.LIVE else None
    observer = observation.observer(frame_builder(job.job_id, trajectories.initial_scene.actors, dt, monitor), dt, last_index=planned_steps) if observation is not None else None
    on_step = step_observer(monitor, observer)
    status(f"running the kinematic {payload.mode.value} run" + (" with the live monitor" if monitor is not None else ""))
    if payload.mode == KinematicMode.REPLAY:
        result = run_kinematic_replay(trajectories, environment=environment, dt=payload.dt, steps=payload.steps, on_step=on_step, hosting=hosting)
    else:
        own = own_ship(trajectories.initial_scene, payload.own_ship_id)
        parameters = own_ship_parameters(payload, trajectories, dt)
        result = run_kinematic_closed_loop(
            trajectories,
            own_ship_id=payload.own_ship_id,
            asv_system=OWN_SHIP_ASV_SYSTEMS[payload.mode],
            usv_navigation_parameters=parameters.get(AsvSystemId.USV_NAVIGATION, {}).get(own.id),
            moos_ivp_parameters=parameters.get(AsvSystemId.MOOS_IVP, {}).get(own.id),
            environment=environment,
            dt=payload.dt,
            steps=payload.steps,
            on_step=on_step,
            hosting=hosting,
        )
    status("run finished", 1.0)
    data: JobResultData = {"run_record": dict(result.run_record), "steps": result.steps, "state_digest": result.state_digest()}
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=result.steps < planned_steps)
    if payload.include_trajectories:
        data["trajectories"] = result.to_trajectories().to_dict()
    return data
