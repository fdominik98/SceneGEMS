"""simulation: one run of every vessel's stack, by the worker node's simulation pool, with the runner the payload names.

The job is one run-simulation request to the worker node's simulation subsystem (jobs/pool_client.py
run_pool_request), so the daemon only relays: it sends the payload with its run seed, passes the control
node's Observe and the operator's Start on as signals, and hands the frames, the log lines and the status the
task publishes to the job's observation and report. The subsystem's task builds the run's stack, starts and
removes its containers and keeps the run's time rules (run_stack below, subsystems/simulation/simulation_worker.py);
the job has no deadline of its own and ends by its task's state, or when the pool stops heartbeating.

The payload is the runner's payload model, chosen by its runner field (simulation_runners/):

    kinematic  replay or USV Navigation on the kinematic layer, the runner stepping the kinematic
               simulator's container (kinematic_runner.py; fields mode, own_ship_id, usv_navigation, early_stop)
    ardupilot  replay or USV Navigation over the lockstep MAVLink adapters on a SITL or Gazebo stack
               per job, the layer named by simulation_layer (ardupilot_sim or gazebo; ardupilot_runner.py;
               fields mode, own_ship_id, usv_navigation as the kinematic runner's)
    gazebo_custom  replay or USV Navigation on the custom controller, the runner stepping a paused
               Gazebo world per job with no SITL (gazebo_custom_runner.py; fields mode, own_ship_id,
               usv_navigation, environment)

Every runner runs on a stack per job in which each layer has its own container: one simulator for
the scenario, and per vessel its controller and its ASV system (simulation_runners/vessel_job_stack.py).
The runner's container owns the clock and carries the messages between them.

The kinematic and ardupilot runners keep the fields, observation, live monitor and result they had
as their own job types (simulation.kinematic, simulation.ardupilot_sim, simulation.gazebo before
protocol 6). The
components a job requires are the layers of the vessel stacks its payload runs (required_components),
so a worker node runs it only with every one of them. A new runner adds its module to RUNNER_MODULES.
"""

import json
import logging
import threading
from typing import TYPE_CHECKING, Annotated, Any, Dict, Mapping, Optional, Set, Tuple, Union

from pydantic import ConfigDict, Field, RootModel

from scenegems_tool.cluster.fingerprints.components import MONITORING, ComponentId, SimulationRunner, StackTriple, ordered, stack_components
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.live_monitor import SimulationMonitor
from scenegems_tool.cluster.worker_node.jobs.pool_client import run_pool_request
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback
from scenegems_tool.cluster.worker_node.jobs.simulation_runners import ardupilot_runner, attended_runner, gazebo_custom_runner, kinematic_runner
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.simulation.simulation_types import (
    OBSERVE_SIGNAL,
    RUN_SIMULATION_TASK,
    SIMULATION_FRAMES_STREAM,
    SIMULATION_LOG_STREAM,
    SIMULATION_RESULT_STREAM,
    START_SIGNAL,
)

if TYPE_CHECKING:
    from types import ModuleType

    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.vessel_stack.hosting import StackHosting

RUNNER_MODULES: Dict[SimulationRunner, "ModuleType"] = {
    SimulationRunner.KINEMATIC: kinematic_runner,
    SimulationRunner.ARDUPILOT: ardupilot_runner,
    SimulationRunner.GAZEBO_CUSTOM: gazebo_custom_runner,
    SimulationRunner.ATTENDED: attended_runner,
}

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (
    ArtifactField("states", ArtifactKind.TRAJECTORIES),  # the ardupilot runner's state log
    ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),
)

RunnerPayload = Annotated[
    Union[
        kinematic_runner.KinematicSimulationPayload,
        ardupilot_runner.ArduPilotSimulationPayload,
        gazebo_custom_runner.GazeboCustomSimulationPayload,
        attended_runner.AttendedSimulationPayload,
    ],
    Field(discriminator="runner"),
]


class SimulationPayload(RootModel[RunnerPayload]):
    """The runner's payload; root holds it."""

    model_config = ConfigDict(frozen=True)

    @property
    def runner(self) -> SimulationRunner:
        return self.root.runner

    def vessel_stacks(self) -> Tuple[StackTriple, ...]:
        """The vessel stacks the run runs, every vessel's."""
        return self.root.vessel_stacks()


PAYLOAD_MODEL = SimulationPayload


def required_components(payload: SimulationPayload) -> Tuple[ComponentId, ...]:
    """Every layer of every vessel's stack, in catalog order, and the monitoring subsystem for a run that is judged while it runs.

    A judged run has its series of scenes in the worker node's monitoring subsystem, so only a worker node that
    runs one takes it, and it takes a monitoring slot there (fingerprints/components.py slot_job_types).
    """
    components = stack_components(payload.vessel_stacks())
    if payload.root.monitor == SimulationMonitor.LIVE:
        return ordered((*components, MONITORING))
    return components


_logger = logging.getLogger(__name__)
_CONTROL_WAIT_S = 0.2  # how long the relay waits for a new request of the observation before it looks whether the run is over


class RunRelay:
    """The daemon's side of a running task: what the task publishes goes to the job's report and observation, what the observation is asked goes to the task."""

    def __init__(self, report: JobReport, observation: Optional[JobObservation]):
        self._report = report
        self._observation = observation
        self._frame_batches: Set[int] = set()
        self._log_batches: Set[int] = set()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.outcome: Optional[Mapping[str, Any]] = None  # the task's result message

    def take(self, stream: str, message: Mapping[str, Any]) -> bool:
        """Keep a message of the run; True once its result and every batch the result counts are here."""
        if stream == SIMULATION_FRAMES_STREAM:
            if message.get("index") not in self._frame_batches:
                self._frame_batches.add(message.get("index"))
                if self._observation is not None:
                    self._observation.add_frames((frame, len(json.dumps(frame))) for frame in message.get("frames") or [])
        elif stream == SIMULATION_LOG_STREAM:
            if message.get("index") not in self._log_batches:
                self._log_batches.add(message.get("index"))
                for line in message.get("lines") or []:
                    self._report.log(str(line.get("source", "")), str(line.get("text", "")), LogStream(line.get("stream", LogStream.STDOUT.value)))
        elif stream == SIMULATION_RESULT_STREAM:
            self.outcome = message
        if self.outcome is None:
            return False
        return len(self._frame_batches) >= int(self.outcome.get("frame-batches", 0)) and len(self._log_batches) >= int(self.outcome.get("log-batches", 0))

    def follow(self, client: Any, request_id: str) -> None:
        """From the moment the task runs: pass every change of the observation's request on to it, on a thread of its own."""
        if self._observation is None:
            return
        self._thread = threading.Thread(target=self._pass_requests, args=(client, request_id, self._observation), name=f"simulation_relay_{request_id}", daemon=True)
        self._thread.start()

    def _pass_requests(self, client: Any, request_id: str, observation: JobObservation) -> None:
        applied = 0  # revision 0 is the request nobody made
        observed: Optional[Tuple[bool, float]] = None
        started = False
        while not self._stop.is_set():
            control = observation.wait_for_change(applied, _CONTROL_WAIT_S)
            if control.revision == applied or self._stop.is_set():
                if observation.closed:
                    return
                continue
            try:
                if (control.active, control.speed) != observed and (control.active or observed is not None):
                    observed = (control.active, control.speed)
                    client.publish_signal(OBSERVE_SIGNAL, request_id, {"active": control.active, "speed": control.speed})
                if control.started and not started:
                    started = True
                    client.publish_signal(START_SIGNAL, request_id)
            except Exception as error:  # the job is over and its connection closed under the relay
                _logger.info("Stopped passing requests to run %s: %s", request_id, error)
                return
            applied = control.revision

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def result(self) -> JobResultData:
        """The job's result from the task's: a run that failed with a reason fails the job with it and its retry rule."""
        outcome = self.outcome or {}
        if outcome.get("error"):
            raise JobFailed(str(outcome["error"]), retryable=bool(outcome.get("retryable", False)))
        result = outcome.get("result")
        if not isinstance(result, Mapping):
            raise JobFailed("the simulation pool answered without a result", retryable=True)
        return dict(result)


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(SimulationPayload, job).root
    relay = RunRelay(report, worker_node.observations.of(job))
    try:
        run_pool_request(
            job,
            worker_node,
            report,
            cancel,
            subsystem=Subsystem.SIMULATION,
            task_name=RUN_SIMULATION_TASK,
            params={"job-id": job.job_id, "attempt": job.attempt, "payload": job.payload},
            seed=payload.seed,
            streams=(SIMULATION_FRAMES_STREAM, SIMULATION_LOG_STREAM, SIMULATION_RESULT_STREAM),
            is_result=relay.take,
            timeout_s=None,  # the task keeps the run's time rules: observed time, the wait for the operator's Start
            pool_description="simulation pool",
            reply_description="simulation result",
            on_running=relay.follow,
            relay_feedback=True,
            relay_detail=True,
        )
    except JobFailed:
        if relay.outcome is None:
            raise
        # The task finished and its result is here; only a batch of frames or log lines before it never arrived
    finally:
        relay.stop()
    return relay.result()


def run_stack(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[Any] = None) -> JobResultData:
    """Run the job's stack with the runner its payload names and return the run's result: what a task of the simulation subsystem runs.

    worker_node is the context the stack is built in (names, folders, the broker); cancel is anything with is_set().
    """
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].run(job, worker_node, report, payload, cancel)


def execute(job: JobSpec, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part of the runner the payload names. hosting is where the stack's layers run: its containers unless given."""
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].execute(job, payload, status, observation=observation, hosting=hosting)
