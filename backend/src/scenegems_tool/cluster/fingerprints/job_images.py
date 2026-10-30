"""The images each job type runs in, named as deploy/scripts/build.sh tags and lists them.

The master requires these images' fingerprints of a job (JobRequirements.fingerprints) and
of a node before it leases to it; a node checks the same list to know what to rebuild, and
the release lists them per capability (cluster/release/roles.py).

A simulation job type names the vessel stacks it runs. Its images are its runner's plus the
containers on those stacks, read from the vessel stack registry, so the availability matrix
decides what a simulation capability installs on a node. The registry is read on first use,
so importing this module (the master does at start) loads neither it nor numpy.
"""

from functools import lru_cache
from typing import TYPE_CHECKING, Collection, Dict, Iterable, Set, Tuple

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId

if TYPE_CHECKING:
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

SCENE_GENERATION_IMAGE = "scenegems-scene-generation-subsystem:latest"
TRAJECTORY_GENERATION_IMAGE = "scenegems-trajectory-generation-subsystem:latest"
SCENARIO_EXECUTION_IMAGE = "scenegems-scenario-execution-subsystem:latest"
MONITORING_IMAGE = "scenegems-monitoring-subsystem:latest"

# The images a job of the type needs besides its vessel stacks: the subsystem it runs in (a simulation's runner)
BASE_JOB_TYPE_IMAGES = {
    JobType.SCENE_GENERATION: (SCENE_GENERATION_IMAGE,),
    JobType.TRAJECTORY_GENERATION: (TRAJECTORY_GENERATION_IMAGE,),
    JobType.SIMULATION_KINEMATIC: (SCENARIO_EXECUTION_IMAGE,),
    JobType.SIMULATION_ARDUPILOT_SIM: (SCENARIO_EXECUTION_IMAGE,),
    JobType.SIMULATION_GAZEBO: (SCENARIO_EXECUTION_IMAGE,),
    JobType.MONITORING_POST_HOC: (MONITORING_IMAGE,),
    JobType.CALIBRATION_DEVIATION: (SCENARIO_EXECUTION_IMAGE,),
}

StackTriple = Tuple[AsvSoftwareId, ControlLayerId, SimulationLayerId]

# The vessel stacks each simulation job type runs (cluster/node/jobs/). Each must be a campaign stack of the matrix:
# available and not workbench only. A stack no type names runs on the workbench only, as a live session.
SIMULATION_JOB_STACKS: Dict[JobType, Tuple[StackTriple, ...]] = {
    JobType.SIMULATION_KINEMATIC: (
        (AsvSoftwareId.REPLAY, ControlLayerId.NONE, SimulationLayerId.KINEMATIC),
        (AsvSoftwareId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC),
    ),
    JobType.SIMULATION_ARDUPILOT_SIM: ((AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),),
    JobType.SIMULATION_GAZEBO: ((AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO),),
}


class JobStackError(ValueError):
    """A simulation job type names a stack the vessel stack matrix does not offer for campaigns."""


def _triple(stack: "VesselStackConfig") -> StackTriple:
    return (stack.asv_software, stack.control_layer, stack.simulation_layer)


def stack_images(stacks: Iterable[StackTriple]) -> Tuple[str, ...]:
    """The image tags of every container on these stacks' chains, sorted. A stack that is not available, or is workbench only, fails."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    resolver = default_resolver()
    images: Set[str] = set()
    for asv_software, control_layer, simulation_layer in stacks:
        stack = VesselStackConfig(asv_software=asv_software, control_layer=control_layer, simulation_layer=simulation_layer)
        chain = resolver.resolve(stack)
        if not chain.available:
            raise JobStackError(f"({stack}) is not available in the vessel stack matrix: {chain.reason}")
        if chain.capabilities.interactive_only:
            raise JobStackError(f"({stack}) is workbench only, so no job may run it")
        images.update(container.default_image for spec in chain.specs for container in spec.containers)
    return tuple(sorted(images))


@lru_cache(maxsize=1)
def job_type_images() -> Dict[JobType, Tuple[str, ...]]:
    """The images every job of each type needs: its base images, then the containers of the stacks a simulation type runs."""
    images = {}
    for job_type, base in BASE_JOB_TYPE_IMAGES.items():
        images[job_type] = base + tuple(image for image in stack_images(SIMULATION_JOB_STACKS.get(job_type, ())) if image not in base)
    return images


def job_images(job_type: JobType) -> Tuple[str, ...]:
    """The images one job of the type runs in."""
    return job_type_images()[job_type]


def capability_images(job_types: Collection[JobType]) -> Set[str]:
    """The images a node that offers these job types must have built."""
    return {image for job_type in job_types for image in job_images(job_type)}


def job_types_of_stack(stack: "VesselStackConfig") -> Tuple[JobType, ...]:
    """The simulation job types that run this stack; empty when it runs on the workbench only."""
    return tuple(job_type for job_type, stacks in SIMULATION_JOB_STACKS.items() if _triple(stack) in stacks)


def unrun_campaign_stacks() -> Tuple["VesselStackConfig", ...]:
    """The campaign stacks of the matrix (available, not workbench only) that no simulation job type runs."""
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    return tuple(chain.stack for chain in default_resolver().availability_matrix() if chain.available and not chain.capabilities.interactive_only and not job_types_of_stack(chain.stack))
