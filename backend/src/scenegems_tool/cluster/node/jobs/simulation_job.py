"""simulation: one run of every vessel's stack, by the runner the payload names.

The payload is the runner's payload model, chosen by its runner field (simulation_runners/):

    kinematic  replay or USV Navigation on the kinematic layer, in process in a scenario execution
               container (kinematic_runner.py; fields mode, own_ship_id, usv_navigation, early_stop)
    ardupilot  replay over the lockstep MAVLink adapter on a SITL or Gazebo stack per job, the layer
               named by simulation_layer (ardupilot_sim or gazebo; ardupilot_runner.py)

Each runner keeps the fields, observation, live monitor and result it had as its own job type
(simulation.kinematic, simulation.ardupilot_sim, simulation.gazebo before protocol 6). The
components a job requires are the layers of the vessel stacks its payload runs (required_components),
so a node runs it only with every one of them. A new runner adds its module to RUNNER_MODULES.
"""

import threading
from typing import TYPE_CHECKING, Annotated, Dict, Optional, Tuple, Union

from pydantic import ConfigDict, Field, RootModel

from scenegems_tool.cluster.fingerprints.components import ComponentId, SimulationRunner, StackTriple, stack_components
from scenegems_tool.cluster.node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback
from scenegems_tool.cluster.node.jobs.simulation_runners import ardupilot_runner, kinematic_runner
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec

if TYPE_CHECKING:
    from types import ModuleType

    from scenegems_tool.cluster.node.jobs.in_container.run_observation import ContainerObservation

RUNNER_MODULES: Dict[SimulationRunner, "ModuleType"] = {
    SimulationRunner.KINEMATIC: kinematic_runner,
    SimulationRunner.ARDUPILOT: ardupilot_runner,
}

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (
    ArtifactField("states", ArtifactKind.TRAJECTORIES),  # the ardupilot runner's state log
    ArtifactField("trajectories", ArtifactKind.TRAJECTORIES),
)

RunnerPayload = Annotated[Union[kinematic_runner.KinematicSimulationPayload, ardupilot_runner.ArduPilotSimulationPayload], Field(discriminator="runner")]


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


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].run(job, node, report, payload, cancel)


def execute(job: JobSpec, status: StatusCallback, observation: Optional["ContainerObservation"] = None) -> JobResultData:
    """The in-container part of the runner the payload names."""
    payload = parse_payload(SimulationPayload, job).root
    return RUNNER_MODULES[payload.runner].execute(job, payload, status, observation=observation)
