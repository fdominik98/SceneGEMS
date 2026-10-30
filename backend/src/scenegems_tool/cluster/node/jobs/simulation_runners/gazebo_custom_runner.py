"""The simulation job's gazebo_custom runner: the custom controller on Gazebo, the world stepped by the runner, on a Gazebo stack per job.

Every vessel runs on the custom control layer (control_layers/custom/): replay through the
line-of-sight waypoint follower, or in mode usv_navigation the own ship (the scene's OS unless
own_ship_id names another vessel) on USV Navigation and the others on replay, as the kinematic
runner's modes are. The node resolves the instance (gz_lockstep_runner.gz_custom_instance),
generates the world and the vessel models into the job's folder and adds a runner from the
scenario execution image on the stack network. The stack has no SITL: the Gazebo service starts
paused with the gz-transport actuator listening (GZ_START_PAUSED, GZ_ACTUATOR_PORT), and the
runner steps the world itself (gz_lockstep_runner.run_gz_custom), so a node with the Gazebo layer
and no SITL runs it.

The payload's environment (wind and waves) goes into the instance, so the generated world and
the hull dynamics the runner's autopilots are tuned from see the same one; the resolver refuses
what the stack does not support.

The runner steps the world, so nothing runs ahead of it: observed live, the run is paced to the
observers' speed and its frames are every step's states (with the live monitor's verdicts on
judged steps), and the observed time does not count against the timeout. The step observer only
reads the states, so the result does not depend on whether the run was observed. The lockstep
runner does not stop early, so the live monitor has no early stop here.
"""

import threading
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import EnvironmentPayload, GeofencePayload, TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.node.jobs.simulation_runners.ardupilot_runner import STACK_NETWORK, frame_builder, observed_trajectories, step_observer
from scenegems_tool.cluster.node.jobs.simulation_runners.kinematic_runner import KinematicMode, UsvNavigationPayload, check_closed_loop_options, own_ship
from scenegems_tool.cluster.node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId

if TYPE_CHECKING:
    from scenegems_tool.cluster.node.jobs.in_container.run_observation import ContainerObservation

GAZEBO_SERVICE = "gazebo"  # the Gazebo service's name on the stack network (generators/gazebo_service_generator.py), where the actuator listens

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)


def vessel_stacks(mode: KinematicMode = KinematicMode.REPLAY) -> Tuple[StackTriple, ...]:
    """The vessel stacks a run of the mode runs: replay on the custom controller, USV Navigation for the own ship in mode usv_navigation."""
    replay = (AsvSoftwareId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)
    if mode == KinematicMode.REPLAY:
        return (replay,)
    return (replay, (AsvSoftwareId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO))


class GazeboCustomSimulationPayload(ProtocolModel):
    runner: Literal[SimulationRunner.GAZEBO_CUSTOM]
    mode: KinematicMode = KinematicMode.REPLAY
    trajectories: TrajectoriesInput
    own_ship_id: Optional[int] = None  # usv_navigation only; the scene's own ship when None
    usv_navigation: Optional[UsvNavigationPayload] = None  # usv_navigation only; from the own ship's trajectory when None
    environment: EnvironmentPayload = Field(default_factory=EnvironmentPayload)  # wind and waves of the world and of the hull dynamics
    geofence: Optional[GeofencePayload] = None  # places the world on the map; the node's reference geofence when None
    dt: Optional[float] = Field(default=None, gt=0.0)  # the trajectories' time step when None; whole control steps of 0.1 s
    steps: Optional[int] = Field(default=None, ge=1)  # the trajectories' timespan when None
    seed: int = 0  # run seed (EnvironmentConfig.seed)
    monitor: SimulationMonitor = SimulationMonitor.NONE
    colregs_constraints_content: Optional[str] = None  # live only: COLREGS constants YAML; the general maritime defaults when None
    include_trajectories: bool = False  # return the observed run as trajectories, as the kinematic runner does
    timeout_s: float = Field(default=1800.0, gt=0.0)

    @model_validator(mode="after")
    def _closed_loop_options_need_closed_loop(self) -> "GazeboCustomSimulationPayload":
        check_closed_loop_options(self.mode, self.own_ship_id, self.usv_navigation)
        return self

    @model_validator(mode="after")
    def _monitor_options_need_the_live_monitor(self) -> "GazeboCustomSimulationPayload":
        if self.monitor != SimulationMonitor.LIVE and self.colregs_constraints_content is not None:
            raise ValueError("colregs_constraints_content applies only to monitor live")
        if (self.monitor == SimulationMonitor.LIVE or self.include_trajectories) and self.dt is not None and not float(self.dt).is_integer():
            raise ValueError("the live monitor and the trajectories need a whole number of seconds as dt")
        return self

    @model_validator(mode="after")
    def _whole_control_steps(self) -> "GazeboCustomSimulationPayload":
        from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import CONTROL_DT_S

        if self.dt is not None and abs(round(self.dt / CONTROL_DT_S) * CONTROL_DT_S - self.dt) > 1e-9:
            raise ValueError(f"dt must be a whole number of the custom controller's {CONTROL_DT_S:g} s control steps")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        return vessel_stacks(self.mode)


PAYLOAD_MODEL = GazeboCustomSimulationPayload


def plain_state(state: Any) -> Any:
    """The Gazebo runner observes ActorStates themselves: the step scene's adapter (ardupilot_runner.step_scene's state_of)."""
    return state


def _instance(payload: GazeboCustomSimulationPayload):
    """The trajectories, the instance and the own ship's USV Navigation parameters (by vessel id, empty in replay); ValueError when own_ship_id names no vessel."""
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import gz_custom_instance

    trajectories = to_trajectories(payload.trajectories)
    asv_software: Dict[int, AsvSoftwareId] = {}
    parameters = {}
    if payload.mode == KinematicMode.USV_NAVIGATION:
        own = own_ship(trajectories.initial_scene, payload.own_ship_id)
        asv_software[own.id] = AsvSoftwareId.USV_NAVIGATION
        if payload.usv_navigation is not None:
            parameters[own.id] = payload.usv_navigation.to_parameters()
    instance = gz_custom_instance(trajectories, asv_software, environment=payload.environment.to_environment(payload.seed))
    return trajectories, instance, parameters


def build_job_stack(job: JobSpec, node: NodeContext, payload: GazeboCustomSimulationPayload) -> JobStack:
    """Resolve the instance, write the world and the vessel models into the job's folder and assemble the stack: the paused Gazebo service and the runner."""
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
    from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts, write_simulation_gen_files

    try:
        trajectories, instance, _ = _instance(payload)
    except ValueError as error:
        raise JobFailed(f"Simulation payload rejected: {error}", retryable=False) from error
    try:
        default_resolver().require_instance(instance, attended=False)
    except StackUnavailableError as error:
        raise JobFailed(f"Simulation stack rejected: {error}", retryable=False) from error
    scope = node.job_scope(job)
    gen_folder = f"{scope.folder}/gen"
    pending_writes, stack_compose = build_simulation_docker_stack_artifacts(
        instance,
        trajectories,
        node.mqtt_connection,
        payload.geofence.to_geofence() if payload.geofence is not None else node.reference_geofence,
        headless=True,
        embedded_in_subsystem=True,
        gen_folder=gen_folder,
    )
    write_simulation_gen_files(pending_writes, gen_folder)
    stack_services = list(stack_compose["services"])
    services = {
        **stack_compose["services"],
        RUNNER_SERVICE: runner_service(subsystem_image(Subsystem.SCENARIO_EXECUTION), networks=[STACK_NETWORK], depends_on=stack_services),
    }
    return JobStack(scope, services, networks=stack_compose["networks"], volumes=stack_compose.get("volumes"))


def run(job: JobSpec, node: NodeContext, report: JobReport, payload: GazeboCustomSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    report.status("generating the Gazebo stack for the custom controller")
    stack = build_job_stack(job, node, payload)
    # The runner steps the world, so an observed run is paced to the observers' speed and that time does not count against the timeout
    return stack.run(job_document(job), report, timeout_s=payload.timeout_s, cancel=cancel, observation=node.observations.of(job), paced=True)


def execute(job: JobSpec, payload: GazeboCustomSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None) -> JobResultData:
    """The in-container part: step the world with every vessel's custom controller and describe the run; observation paces it and forwards its states."""
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import run_gz_custom

    trajectories, instance, parameters = _instance(payload)
    dt = float(trajectories.time_step) if payload.dt is None else payload.dt
    steps = payload.steps if payload.steps is not None else int(round(trajectories.timespan / dt))
    monitor = LiveMonitor(trajectories.initial_scene.actors, int(dt), payload.colregs_constraints_content, early_stop=False) if payload.monitor == SimulationMonitor.LIVE else None
    observer = observation.observer(frame_builder(job.job_id, trajectories, dt, monitor, state_of=plain_state), dt, last_index=steps) if observation is not None else None
    on_step = step_observer(trajectories, monitor, observer, state_of=plain_state)
    status(f"connecting to the Gazebo actuator for the {payload.mode.value} run" + (" with the live monitor" if monitor is not None else ""))
    result = run_gz_custom(trajectories, instance, host=GAZEBO_SERVICE, dt=payload.dt, steps=payload.steps, usv_navigation_parameters=parameters or None, on_step=on_step)
    status("run finished", 1.0)
    data: JobResultData = {
        "run_record": dict(result.run_record),
        "steps": result.steps,
        "achieved_speedup": result.achieved_speedup,
        "late_commands": result.late_commands,
        "state_digest": result.state_digest(),
    }
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=False)
    if payload.include_trajectories:
        data["trajectories"] = observed_trajectories(trajectories, result, dt, state_of=plain_state).to_dict()
    return data
