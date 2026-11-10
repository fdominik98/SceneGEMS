"""simulation: one run of every vessel's stack, by the runner the payload names.

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
the scenario, and per vessel its controller and its ASV software (simulation_runners/vessel_job_stack.py).
The runner's container owns the clock and carries the messages between them.

The kinematic and ardupilot runners keep the fields, observation, live monitor and result they had
as their own job types (simulation.kinematic, simulation.ardupilot_sim, simulation.gazebo before
protocol 6). The
components a job requires are the layers of the vessel stacks its payload runs (required_components),
so a worker node runs it only with every one of them. A new runner adds its module to RUNNER_MODULES.
"""

import threading
from typing import TYPE_CHECKING, Annotated, Dict, Optional, Tuple, Union

from pydantic import ConfigDict, Field, RootModel

from scenegems_tool.cluster.fingerprints.components import ComponentId, SimulationRunner, StackTriple, stack_components
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.runner_container import StatusCallback
from scenegems_tool.cluster.worker_node.jobs.simulation_runners import ardupilot_runner, gazebo_custom_runner, kinematic_runner
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

if TYPE_CHECKING:
    from types import ModuleType

    from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation
    from scenegems_tool.vessel_stack.hosting import StackHosting

RUNNER_MODULES: Dict[SimulationRunner, "ModuleType"] = {
    SimulationRunner.KINEMATIC: kinematic_runner,
    SimulationRunner.ARDUPILOT: ardupilot_runner,
    SimulationRunner.GAZEBO_CUSTOM: gazebo_custom_runner,
}

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (
    ArtifactField("states", ArtifactKind.TRAJECTORIES),  # the ardupilot runner's state log
    ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),
)

RunnerPayload = Annotated[
    Union[kinematic_runner.KinematicSimulationPayload, ardupilot_runner.ArduPilotSimulationPayload, gazebo_custom_runner.GazeboCustomSimulationPayload], Field(discriminator="runner")
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
    """Every layer of every vessel's stack, in catalog order."""
    return stack_components(payload.vessel_stacks())


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].run(job, worker_node, report, payload, cancel)


def execute(job: JobSpec, status: StatusCallback, observation: Optional["ContainerObservation"] = None, hosting: Optional["StackHosting"] = None) -> JobResultData:
    """The in-container part of the runner the payload names. hosting is where the stack's layers run: its containers unless given."""
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].execute(job, payload, status, observation=observation, hosting=hosting)
