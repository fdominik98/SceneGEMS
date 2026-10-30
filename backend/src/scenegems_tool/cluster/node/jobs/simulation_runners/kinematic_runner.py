"""The simulation job's kinematic runner: a lockstep run on the kinematic layer, in a scenario execution container.

Two modes: replay of every vessel's generated trajectory (kinematic_runner.run_kinematic_replay),
or USV Navigation on the own ship against replaying targets (run_kinematic_closed_loop).
The run needs no other service, so its container has no network. A run is bit-identical
for the same payload, and the result carries its state digest.

With monitor live, the COLREGS monitor judges every step in process (live_monitor.py) with the
post-hoc monitor's summary (subsystems/monitoring/rule_outcomes.py), and early_stop ends the run once
every rule is decided. A run without a monitor is the same run as before the monitor existed.

Observed live (the node's observation, in_container/run_observation.py), the run is paced to
the observers' speed and writes frames: every vessel's state at the step and, with the live
monitor, its outcomes. The step observer only reads the states, so the digest and the result
do not depend on whether or when the run was observed.
"""

import threading
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import DEFAULT_PRESCRIBED_TIME_S, UsvNavigationParameters
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId

if TYPE_CHECKING:
    from scenegems_tool.cluster.node.jobs.in_container.run_observation import ContainerObservation

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)


class KinematicMode(str, Enum):
    REPLAY = "replay"  # every vessel replays its trajectory
    USV_NAVIGATION = "usv_navigation"  # the own ship runs USV Navigation, the others replay


def vessel_stacks(mode: KinematicMode) -> Tuple[StackTriple, ...]:
    """The vessel stacks a run of the mode runs: replay for the vessels that replay, USV Navigation for the own ship in mode usv_navigation."""
    replay = (AsvSoftwareId.REPLAY, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)
    if mode == KinematicMode.REPLAY:
        return (replay,)
    return (replay, (AsvSoftwareId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC))


class UsvNavigationPayload(ProtocolModel):
    """UsvNavigationParameters in full; leave it out for the SceneGEMS defaults (from_reference)."""

    goal: Tuple[float, float]
    speed: float = Field(gt=0.0)
    safety_radius: float = Field(gt=0.0)
    control_horizon: float = Field(gt=0.0)
    prescribed_time: float = Field(default=DEFAULT_PRESCRIBED_TIME_S, gt=0.0)
    runtime_options: Dict[str, float] = Field(default_factory=dict)

    def to_parameters(self) -> UsvNavigationParameters:
        return UsvNavigationParameters(
            goal=self.goal,
            speed=self.speed,
            safety_radius=self.safety_radius,
            control_horizon=self.control_horizon,
            prescribed_time=self.prescribed_time,
            runtime_options=tuple(sorted(self.runtime_options.items())),
        )


def check_closed_loop_options(mode: KinematicMode, own_ship_id: Optional[int], usv_navigation: Optional[UsvNavigationPayload]) -> None:
    """own_ship_id and usv_navigation apply only to mode usv_navigation (every runner with the two modes checks it)."""
    if mode == KinematicMode.REPLAY and (own_ship_id is not None or usv_navigation is not None):
        raise ValueError("own_ship_id and usv_navigation apply only to mode usv_navigation")


def own_ship(scene, own_ship_id: Optional[int]):
    """The vessel that runs USV Navigation: the scene's own ship, or the vessel own_ship_id names; ValueError when the scene has none by that id."""
    own = scene.os if own_ship_id is None else next((vessel for vessel in scene.vessels if vessel.id == own_ship_id), None)
    if own is None:
        raise ValueError(f"No vessel with id {own_ship_id} in the scene")
    return own


class KinematicSimulationPayload(ProtocolModel):
    runner: Literal[SimulationRunner.KINEMATIC]
    mode: KinematicMode = KinematicMode.REPLAY
    trajectories: TrajectoriesInput
    own_ship_id: Optional[int] = None  # usv_navigation only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only
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
        check_closed_loop_options(self.mode, self.own_ship_id, self.usv_navigation)
        return self

    @model_validator(mode="after")
    def _monitor_options_need_the_live_monitor(self) -> "KinematicSimulationPayload":
        if self.monitor != SimulationMonitor.LIVE and (self.early_stop or self.colregs_constraints_content is not None):
            raise ValueError("early_stop and colregs_constraints_content apply only to monitor live")
        if self.monitor == SimulationMonitor.LIVE and self.dt is not None and not float(self.dt).is_integer():
            raise ValueError("the live monitor needs a whole number of seconds as dt")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        return vessel_stacks(self.mode)


PAYLOAD_MODEL = KinematicSimulationPayload


def run(job: JobSpec, node: NodeContext, report: JobReport, payload: KinematicSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    return run_in_runner_container(job, node, report, Subsystem.SCENARIO_EXECUTION, timeout_s=payload.timeout_s, cancel=cancel)


def frame_builder(scenario_id: str, actors, dt: float, monitor: Optional[LiveMonitor]) -> Callable[[int, Any], Dict[str, Any]]:
    """A step's frame in the workbench's wire format: the monitored scene when the live monitor judged the step, else the scene alone."""
    from concrete_level.trajectory_generation.scene_builder import SceneBuilder
    from scenegems_tool.gateway.serialization import serialize_frame, serialize_monitored_frame

    actors = tuple(actors)
    time_step = int(dt) if float(dt).is_integer() else dt

    def build(index: int, states) -> Dict[str, Any]:
        timestamp = index * time_step
        if monitor is not None and monitor.last_monitored_index == index:
            return serialize_monitored_frame(scenario_id=scenario_id, monitored_scene=monitor.last_monitored, timestamp=timestamp, time_step=time_step)
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


def execute(job: JobSpec, payload: KinematicSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None) -> JobResultData:
    """The in-container part: run the simulation in process and describe the run; observation makes it observable live."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_closed_loop, run_kinematic_replay

    trajectories = to_trajectories(payload.trajectories)
    environment = EnvironmentConfig.calm(seed=payload.seed)
    dt = float(trajectories.time_step) if payload.dt is None else payload.dt
    planned_steps = payload.steps if payload.steps is not None else int(round(trajectories.timespan / dt))
    monitor = LiveMonitor(trajectories.initial_scene.actors, int(dt), payload.colregs_constraints_content, payload.early_stop) if payload.monitor == SimulationMonitor.LIVE else None
    observer = observation.observer(frame_builder(job.job_id, trajectories.initial_scene.actors, dt, monitor), dt, last_index=planned_steps) if observation is not None else None
    on_step = step_observer(monitor, observer)
    status(f"running the kinematic {payload.mode.value} run" + (" with the live monitor" if monitor is not None else ""))
    if payload.mode == KinematicMode.REPLAY:
        result = run_kinematic_replay(trajectories, environment=environment, dt=payload.dt, steps=payload.steps, on_step=on_step)
    else:
        parameters = payload.usv_navigation.to_parameters() if payload.usv_navigation is not None else None
        result = run_kinematic_closed_loop(
            trajectories, own_ship_id=payload.own_ship_id, usv_navigation_parameters=parameters, environment=environment, dt=payload.dt, steps=payload.steps, on_step=on_step
        )
    status("run finished", 1.0)
    data: JobResultData = {"run_record": dict(result.run_record), "steps": result.steps, "state_digest": result.state_digest()}
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=result.steps < planned_steps)
    if payload.include_trajectories:
        data["trajectories"] = result.to_trajectories().to_dict()
    return data
