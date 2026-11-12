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
SimulationModelsBody). A vessel's name is the vessel's (os, ts1), never one typed on the workbench.

A setup with a real vessel runs every vessel through its ArduAgent over MQTT instead
(subsystems/simulation/arduagent_simulation_driver.py): the real vessel through the agent on board,
at the topic the operator gave, and each simulated vessel through an ArduAgent of the job's stack,
at <root>/unit/surface/simulation/<vessel>-<job>. The broker is the cluster's (root scenegems)
unless the payload names another (root waraps). Such a run is ready to start only when every
vessel is connected, reports its position, is at its start point and, when commanded, armable;
until then the job's status says what each vessel lacks (STATUS_VESSELS).

With monitor live the COLREGS monitor judges every step as a series of the worker node's monitoring subsystem (live_monitor.py), and the
result carries the run record, the state digest, the monitor's summary and the observed
trajectories, as the other runners' do.
"""

import threading
from typing import TYPE_CHECKING, Any, Callable, Dict, Literal, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.fingerprints.components import SimulationRunner, StackTriple
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.messages import PHASE_PREPARING, PHASE_READY_TO_START, PHASE_RUNNING, STATUS_PHASE, STATUS_VESSELS
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.instance_scope import short_job_id
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import GeofencePayload, TrajectoriesInput, to_trajectories
from scenegems_tool.cluster.worker_node.jobs.live_monitor import LiveMonitor, SimulationMonitor
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback, job_document
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.vessel_job_stack import build_vessel_job_stack, ground_control_ports
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.topic_layout import CLUSTER_TOPIC_ROOT, SIMULATION_CONTEXT, WARAPS_TOPIC_ROOT, unit_topic
from scenegems_tool.subsystems.simulation.simulation_types import SIMULATION_SERVICE_NAME

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
    from scenegems_tool.vessel_stack.hosting import StackHosting

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
DEFAULT_START_TIMEOUT_S = 3600.0  # how long a stack waits for its operator before the job gives its slot back
WAITING_FRAME_INTERVAL_S = 2.0  # how often the scene the run starts from is shown again while it waits


DEFAULT_SERVICE_NAME = SIMULATION_SERVICE_NAME  # the runner's name on the broker when its launcher gave it none


def simulation_instance(simulation: Dict[str, Any], seed: int = 0, *, job_id: str = "", topic_root: str = CLUSTER_TOPIC_ROOT) -> "SimulationInstanceConfig":
    """The instance of a workbench setup, with every vessel named as the vessel (os, ts1) whatever the setup calls it.

    A simulated vessel's agent is at <topic_root>/unit/surface/simulation/<vessel>-<job>, so two jobs on one broker never
    share a topic (without a job id, as when a payload is only validated, the name is the vessel's alone). A real
    vessel keeps the topic the setup gives it: that is where the agent on board publishes.

    ValueError for a setup the gateway's conversion refuses, or a real vessel without a usable topic.
    """
    from scenegems_tool.gateway.protocol import simulation_config_from_body
    from scenegems_tool.vessel_stack.contracts.stack_services import vessel_stack_name

    try:
        instance = simulation_config_from_body(simulation)  # type: ignore[arg-type]
    except (KeyError, TypeError) as error:
        raise ValueError(f"the simulation setup is incomplete: {error!r}") from error
    if not instance.vessels:
        raise ValueError("the simulation setup names no vessel")
    topics: Dict[str, str] = {}
    for agent_id, vessel in instance.vessels.items():
        connection = vessel.require_connection()
        name = vessel_stack_name(agent_id)
        connection.agent_name = name
        if vessel.is_simulated:
            connection.topic = unit_topic(topic_root, SIMULATION_CONTEXT, f"{name}-{short_job_id(job_id)}" if job_id else name)
        else:
            connection.topic = _real_vessel_topic(name, connection.topic)
        if connection.topic in topics:
            raise ValueError(f"vessels {topics[connection.topic]} and {name} have the same topic {connection.topic!r}")
        topics[connection.topic] = name
    instance.environment.seed = seed
    return instance


def _real_vessel_topic(name: str, topic: Any) -> str:
    """The base topic of a real vessel's agent as the setup gives it, without a trailing slash."""
    topic = topic.strip().rstrip("/") if isinstance(topic, str) else ""
    if not topic or "+" in topic or "#" in topic:
        raise ValueError(f"the real vessel {name} needs the topic of its agent on the broker, without wildcards: {topic!r}")
    return topic


class BrokerPayload(ProtocolModel):
    """The broker of a run with a real vessel when it is not the cluster's: an external one such as WARA-PS's, whose first topic level is waraps."""

    host: str = Field(min_length=1)
    port: int = Field(gt=0, lt=65536)
    tls: bool = False
    allow_certificates: bool = False  # with TLS: take the broker's certificate without verifying it
    user: str = ""
    password: str = ""

    def connection(self) -> "MQttConnectionInfo":
        from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo

        return MQttConnectionInfo(
            user=self.user,
            password=self.password,
            agent_broker=self.host,
            client_broker=self.host,
            port=self.port,
            tls_connection=self.tls,
            allow_certificates=self.allow_certificates,
            topic_root=WARAPS_TOPIC_ROOT,
        )


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
    broker: Optional[BrokerPayload] = None  # with a real vessel: the broker its agent is on; the cluster's when None

    @property
    def topic_root(self) -> str:
        """The first topic level of the run's broker: scenegems on the cluster's, waraps on an external one."""
        return CLUSTER_TOPIC_ROOT if self.broker is None else WARAPS_TOPIC_ROOT

    def instance(self, job_id: str = "") -> "SimulationInstanceConfig":
        return simulation_instance(self.simulation, self.seed, job_id=job_id, topic_root=self.topic_root)

    @model_validator(mode="after")
    def _the_setup_is_an_instance(self) -> "AttendedSimulationPayload":
        instance = self.instance()
        if self.broker is not None and all(vessel.is_simulated for vessel in instance.vessels.values()):
            raise ValueError("broker applies only to a setup with a real vessel: simulated vessels alone talk to no broker")
        if self.monitor != SimulationMonitor.LIVE and self.colregs_constraints_content is not None:
            raise ValueError("colregs_constraints_content applies only to monitor live")
        return self

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        """Every vessel's stack, once each."""
        instance = self.instance()
        stacks = {(vessel.stack.asv_system, vessel.stack.control_layer, vessel.stack.simulation_layer) for vessel in instance.vessels.values()}
        return tuple(sorted(stacks, key=lambda stack: tuple(layer.value for layer in stack)))


PAYLOAD_MODEL = AttendedSimulationPayload


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, payload: AttendedSimulationPayload, cancel: Optional[threading.Event] = None) -> JobResultData:
    report.status("generating the attended stack", None, {STATUS_PHASE: PHASE_PREPARING})
    try:
        instance = payload.instance(job.job_id)
        trajectories = to_trajectories(payload.trajectories)
    except ValueError as error:
        raise JobFailed(f"Simulation payload rejected: {error}", retryable=False) from error
    stack = build_vessel_job_stack(
        job,
        worker_node,
        instance,
        trajectories,
        payload.geofence.to_geofence(),
        attended=True,
        monitored=payload.monitor == SimulationMonitor.LIVE,
        mqtt_connection=None if payload.broker is None else payload.broker.connection(),
        service_name=worker_node.job_scope(job).instance_id,  # simulation-subsystem-<job>: the runner's name on the broker
    )
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


class _VesselReadiness:
    """Tells the job's status what the vessels of an ArduAgent run still lack, each time that changes, and keeps the subsystem's heartbeat going."""

    def __init__(self, driver: Any, instance: "SimulationInstanceConfig", status: StatusCallback):
        self._driver = driver
        self._names = {agent_id: vessel.require_connection().agent_name for agent_id, vessel in instance.vessels.items()}
        self._status = status
        self._reported: Optional[Dict[str, Dict[str, bool]]] = None
        self.ready = False

    def __call__(self) -> None:
        self._driver.heartbeat()
        states = self._driver.vessel_states()
        if states == self._reported:
            return
        self._reported = states
        self.ready = bool(states) and all(all(state.values()) for state in states.values())
        phase = PHASE_READY_TO_START if self.ready else PHASE_PREPARING
        self._status("ready to start" if self.ready else f"waiting for the vessels ({self.lacking()})", None, {STATUS_PHASE: phase, STATUS_VESSELS: states})

    def lacking(self) -> str:
        """Per vessel that is not ready, what its agent does not report yet: os: armable, at_start."""
        waiting = {agent_id: [key for key, met in state.items() if not met] for agent_id, state in (self._reported or {}).items()}
        return "; ".join(f"{self._names.get(agent_id, agent_id)}: {', '.join(keys)}" for agent_id, keys in waiting.items() if keys)


def _wait_for_the_start(observation: "ContainerObservation", start_timeout_s: float, first_frame: Callable[[], Dict[str, Any]], readiness: Optional[_VesselReadiness] = None) -> None:
    """Waits for the operator's Start; while the run waits, an observer sees the scene it starts from. JobFailed when the Start does not come.

    readiness, of a run with a real vessel, is asked at every look: the control node takes a Start only while the status says the vessels are ready.
    """
    shown_at: Dict[str, float] = {}

    def show_the_start() -> None:
        if readiness is not None:
            readiness()
        now = observation.now()
        if observation.control().active and now - shown_at.get("at", -WAITING_FRAME_INTERVAL_S) >= WAITING_FRAME_INTERVAL_S:
            shown_at["at"] = now
            observation.write_frame(first_frame())

    if not observation.wait_for_start(start_timeout_s, while_waiting=show_the_start):
        if readiness is not None and not readiness.ready:
            raise JobFailed(f"the vessels were not ready to start within {start_timeout_s:g} s ({readiness.lacking()})", retryable=False)
        raise JobFailed(f"nobody started the run within {start_timeout_s:g} s", retryable=False)


def arduagent_driver(payload: AttendedSimulationPayload, instance: "SimulationInstanceConfig", trajectories: Any) -> Any:
    """The driver of a run with a real vessel, on the broker and under the name the launcher gave the runner's container."""
    from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, service_name_from_environment
    from scenegems_tool.subsystems.simulation.arduagent_simulation_driver import ArduAgentSimulationDriver

    return ArduAgentSimulationDriver(instance, trajectories, payload.geofence.to_geofence(), MQttConnectionInfo.from_environment(), service_name_from_environment(DEFAULT_SERVICE_NAME))


def execute(job: JobSpec, payload: AttendedSimulationPayload, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part: wait for the operator's Start, drive the instance and describe the run.

    An instance of simulated vessels runs in lockstep and is ready at once; one with a real vessel runs through the
    vessels' ArduAgents and is ready when they are. Without an observation nobody can start the run, so it starts at
    once (a direct call, as tests make). hosting is where the stack's layers run: its containers unless given
    (vessel_stack/hosting.py).
    """
    from scenegems_tool.subsystems.simulation.lockstep_simulation_driver import LockstepSimulationDriver, uses_lockstep_driver

    trajectories = to_trajectories(payload.trajectories)
    instance = payload.instance(job.job_id)
    if uses_lockstep_driver(instance):
        driver = LockstepSimulationDriver(instance, trajectories, payload.geofence.to_geofence(), hosting=(lambda: hosting) if hosting is not None else None)
        return _run_attended(job, payload, status, observation, trajectories, instance, driver, None)
    driver = arduagent_driver(payload, instance, trajectories)
    try:
        try:
            driver.connect()
        except RuntimeError as error:
            raise JobFailed(f"the run's broker cannot be reached: {error}", retryable=False) from error
        return _run_attended(job, payload, status, observation, trajectories, instance, driver, _VesselReadiness(driver, instance, status))
    finally:
        driver.close()


def _until_the_start(
    status: StatusCallback, observation: Optional["ContainerObservation"], start_timeout_s: float, first_frame: Callable[[], Dict[str, Any]], readiness: Optional[_VesselReadiness]
) -> None:
    """Says that the run is ready to start, or what its vessels lack, and waits for the Start when somebody can give it."""
    if readiness is None:
        status("ready to start", None, {STATUS_PHASE: PHASE_READY_TO_START})
    else:
        readiness()
    if observation is not None:
        _wait_for_the_start(observation, start_timeout_s, first_frame, readiness)


def _driven(driver: Any, on_scene: Callable[[float, Any], None], readiness: Optional[_VesselReadiness]) -> Any:
    """The driver's run; JobFailed when it was stopped, or started while a vessel was not ready."""
    from scenegems_tool.subsystems.simulation.arduagent_simulation_driver import VesselsNotReady

    try:
        result = driver.run(on_scene, threading.Event())
    except VesselsNotReady as error:
        raise JobFailed(f"{error}" + (f" ({readiness.lacking()})" if readiness is not None else ""), retryable=False) from error
    if result is None:
        raise JobFailed("the run was stopped before it ended", retryable=False)
    return result


def _run_attended(
    job: JobSpec,
    payload: AttendedSimulationPayload,
    status: StatusCallback,
    observation: Optional["ContainerObservation"],
    trajectories: Any,
    instance: "SimulationInstanceConfig",
    driver: Any,
    readiness: Optional[_VesselReadiness],
) -> JobResultData:
    """Wait for the Start, run the driver and describe what it observed. readiness is that of a run with a real vessel, None for a lockstep run."""
    from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
    from scenegems_tool.gateway.serialization import serialize_frame

    dt = float(trajectories.time_step)
    time_step = int(dt) if dt.is_integer() else dt
    steps = int(round(trajectories.timespan / dt))
    actors = tuple(trajectories.initial_scene.actors)
    monitor = LiveMonitor(actors, int(dt), payload.colregs_constraints_content, early_stop=False, job=job) if payload.monitor == SimulationMonitor.LIVE else None

    def frame(index: int, scene) -> Dict[str, Any]:
        judged = monitor.frame_of(index) if monitor is not None else None
        if judged is not None:
            return judged
        return serialize_frame(scenario_id=job.job_id, scene=scene, timestamp=index * time_step, time_step=time_step)

    # Before the Start an observer sees where the vessels are: the scene the run starts from, or where their agents report them
    _until_the_start(status, observation, payload.start_timeout_s, lambda: serialize_frame(scenario_id=job.job_id, scene=driver.current_scene, timestamp=0, time_step=time_step), readiness)

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

    result = _driven(driver, on_scene, readiness)
    status("run finished", 1.0, {STATUS_PHASE: PHASE_RUNNING})
    run_record, run_steps, state_digest = _described(result, dt)
    data: JobResultData = {"run_record": run_record, "steps": run_steps, "state_digest": state_digest}
    if monitor is not None:
        data["monitor"] = monitor.result(stopped_early=False)
    if payload.include_trajectories:
        data["trajectories"] = builder.build().to_dict()
    return data
