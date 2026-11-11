"""The simulation job's attended runner: a run with an operator beside it, on a stack per job.

An attended run is what the workbench sets up vessel by vessel: any simulation layer, any control
layer and ASV system per vessel, wind and waves, and Mission Planner on a vessel the operator
steers by hand. Campaigns never run it. The job brings the stack up, reports that it is ready to
start and waits for the operator's Start (StartJob, in_container/run_observation.py
wait_for_start); the wait does not count against the job's timeout. Then the runner drives the
instance with the lockstep runner its stacks resolve to (subsystems/simulation/
lockstep_simulation_driver.py), at the instance's speed-up, and the job ends with the run: another
run is another job.

A Mission Planner vessel is not commanded: its MAVProxy publishes a ground control station port on
the worker node's host, which the job reports in its status detail (STATUS_GROUND_CONTROL), and the
run observes the vessel the operator steers.

The payload's simulation is the workbench's setup as the console sends it (gateway/protocol.py
SimulationModelsBody). Every vessel is simulated: a real vessel is driven through its ArduAgent
over MQTT, which this runner does not do yet.

With monitor live the COLREGS monitor judges every step in process (live_monitor.py), and the
result carries the run record, the state digest, the monitor's summary and the observed
trajectories, as the other runners' do.
"""

import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.messages import PHASE_PREPARING, PHASE_READY_TO_START, PHASE_RUNNING, STATUS_PHASE
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import GeofencePayload, TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.worker_node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack, ground_control_ports
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
    from scenegems_tool.vessel_stack.hosting import StackHosting

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
DEFAULT_START_TIMEOUT_S = 3600.0  # how long a stack waits for its operator before the job gives its slot back
WAITING_FRAME_INTERVAL_S = 2.0  # how often the scene the run starts from is shown again while it waits


def simulation_instance(simulation: Dict[str, Any], seed: int = 0) -> "SimulationInstanceConfig":
    """The instance of a workbench setup, with every vessel's services named as the vessel (os, ts1).

    ValueError for a setup the gateway's conversion refuses, or one with a real vessel.
    """
    from scenegems_tool.gateway.protocol import simulation_config_from_body
    from scenegems_tool.vessel_stack.contracts.stack_services import vessel_stack_name

    try:
        instance = simulation_config_from_body(simulation)  # type: ignore[arg-type]
    except (KeyError, TypeError) as error:
        raise ValueError(f"the simulation setup is incomplete: {error!r}") from error
    real = sorted(agent_id for agent_id, vessel in instance.vessels.items() if not vessel.is_simulated)
    if real:
        raise ValueError(f"a real vessel ({', '.join(real)}) cannot take part in an attended job yet")
    if not instance.vessels:
        raise ValueError("the simulation setup names no vessel")
    for agent_id, vessel in instance.vessels.items():
        if vessel.connection is not None:
            vessel.connection.agent_name = vessel_stack_name(agent_id)
    instance.environment.seed = seed
    return instance


class AttendedSimulationPayload(ProtocolModel):
    runner: Literal[SimulationRunner.ATTENDED]
    simulation: Dict[str, Any]  # the workbench's setup: simulatorType, windVector, wave, simulationSpeed, connectionsByAgentId
    trajectories: TrajectoriesInput
    geofence: GeofencePayload  # the reference frame of the scenario on the map
    seed: int = 0  # run seed (EnvironmentConfig.seed)
    monitor: SimulationMonitor = SimulationMonitor.NONE
    colregs_constraints_content: Optional[str] = None  # live only: COLREGS constants YAML; the general maritime defaults when None
    include_trajectories: bool = True  # return the observed trajectories, not only the run record
    start_timeout_s: float = Field(default=DEFAULT_START_TIMEOUT_S, gt=0.0)  # how long the stack waits for the operator's Start
    timeout_s: float = Field(default=3600.0, gt=0.0)  # the run's own time, from the Start

    @model_validator(mode="after")
    def _the_setup_is_an_instance_of_simulated_vessels(self) -> "AttendedSimulationPayload":
        simulation_instance(self.simulation, self.seed)
        if self.monitor != SimulationMonitor.LIVE and self.colregs_constraints_content is not None:
            raise ValueError("colregs_constraints_content applies only to monitor live")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        """Every vessel's stack, once each."""
        instance = simulation_instance(self.simulation, self.seed)
        stacks = {(vessel.stack.asv_system, vessel.stack.control_layer, vessel.stack.simulation_layer) for vessel in instance.vessels.values()}
        return tuple(sorted(stacks, key=lambda stack: tuple(layer.value for layer in stack)))


PAYLOAD_MODEL = AttendedSimulationPayload


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, payload: AttendedSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    report.status("generating the attended stack", None, {STATUS_PHASE: PHASE_PREPARING})
    try:
        instance = simulation_instance(payload.simulation, payload.seed)
        trajectories = to_trajectories(payload.trajectories)
    except ValueError as error:
        raise JobFailed(f"Simulation payload rejected: {error}", retryable=False) from error
    stack = build_vessel_job_stack(job, worker_node, instance, trajectories, payload.geofence.to_geofence(), attended=True)
    # The run follows the instance's own speed-up, not the observers', and its time counts from the operator's Start
    return stack.run(
        job_document(job),
        report,
        timeout_s=payload.timeout_s,
        cancel=cancel,
        observation=worker_node.observations.of(job),
        paced=False,
        start_timeout_s=payload.start_timeout_s,
        published_ports=ground_control_ports(instance),
    )


def _described(result: Any, dt: float) -> Tuple[Dict[str, Any], int, str]:
    """The run record, the steps and the state digest of what the lockstep runner returned.

    The MAVLink and the Gazebo runner return their run with its record; the kinematic runner returns the run of the
    instance, whose record is written here as the kinematic job writes its own (stacks and specs first).
    """
    if hasattr(result, "record"):
        return result.record(dt, stacks=result.stacks, specs=result.spec_ids), result.result.steps, result.result.state_digest()
    return dict(result.run_record), result.steps, result.state_digest()


def _wait_for_the_start(observation: "ContainerObservation", start_timeout_s: float, first_frame: Callable[[], Dict[str, Any]]) -> None:
    """Waits for the operator's Start; while the run waits, an observer sees the scene it starts from. JobFailed when the Start does not come."""
    shown_at: Dict[str, float] = {}

    def show_the_start() -> None:
        now = observation.now()
        if observation.control().active and now - shown_at.get("at", -WAITING_FRAME_INTERVAL_S) >= WAITING_FRAME_INTERVAL_S:
            shown_at["at"] = now
            observation.write_frame(first_frame())

    if not observation.wait_for_start(start_timeout_s, while_waiting=show_the_start):
        raise JobFailed(f"nobody started the run within {start_timeout_s:g} s", retryable=False)


def execute(job: JobSpec, payload: AttendedSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part: wait for the operator's Start, drive the instance in lockstep and describe the run.

    Without an observation nobody can start the run, so it starts at once (a direct call, as tests make).
    hosting is where the stack's layers run: its containers unless given (vessel_stack/hosting.py).
    """
    from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
    from scenegems_tool.gateway.serialization import serialize_frame, serialize_monitored_frame
    from scenegems_tool.subsystems.simulation.lockstep_simulation_driver import LockstepSimulationDriver

    trajectories = to_trajectories(payload.trajectories)
    instance = simulation_instance(payload.simulation, payload.seed)
    driver = LockstepSimulationDriver(instance, trajectories, payload.geofence.to_geofence(), hosting=(lambda: hosting) if hosting is not None else None)
    dt = float(trajectories.time_step)
    time_step = int(dt) if dt.is_integer() else dt
    steps = int(round(trajectories.timespan / dt))
    actors = tuple(trajectories.initial_scene.actors)
    monitor = LiveMonitor(actors, int(dt), payload.colregs_constraints_content, early_stop=False) if payload.monitor == SimulationMonitor.LIVE else None

    def frame(index: int, scene) -> Dict[str, Any]:
        if monitor is not None and monitor.last_monitored_index == index:
            return serialize_monitored_frame(scenario_id=job.job_id, monitored_scene=monitor.last_monitored, timestamp=index * time_step, time_step=time_step)
        return serialize_frame(scenario_id=job.job_id, scene=scene, timestamp=index * time_step, time_step=time_step)

    status("ready to start", None, {STATUS_PHASE: PHASE_READY_TO_START})
    if observation is not None:
        _wait_for_the_start(observation, payload.start_timeout_s, lambda: serialize_frame(scenario_id=job.job_id, scene=trajectories.initial_scene, timestamp=0, time_step=time_step))

    status(f"running the attended {driver.kind} run" + (" with the live monitor" if monitor is not None else ""), 0.0, {STATUS_PHASE: PHASE_RUNNING})
    observer = observation.observer(frame, dt, last_index=steps, pace=False, stride_speed=float(max(instance.speedup, 1))) if observation is not None else None
    builder = TrajectoryBuilder(time_step=int(dt))

    def on_scene(scenario_time_s: float, scene) -> None:
        index = int(round(scenario_time_s / dt))
        if monitor is not None:
            monitor.on_step(index, [scene[actor] for actor in monitor.actors])
        builder.add_scene_as_dict({actor: scene[actor] for actor in actors})
        if observer is not None:
            observer.step(index, scene)

    result = driver.run(on_scene, threading.Event())
    if result is None:
        raise JobFailed("the run was stopped before it ended", retryable=False)
    status("run finished", 1.0, {STATUS_PHASE: PHASE_RUNNING})
    run_record, run_steps, state_digest = _described(result, dt)
    data: JobResultData = {"run_record": run_record, "steps": run_steps, "state_digest": state_digest}
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=False)
    if payload.include_trajectories:
        data["trajectories"] = builder.build().to_dict()
    return data
