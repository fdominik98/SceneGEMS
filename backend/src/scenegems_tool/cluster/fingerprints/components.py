"""The component catalog: what a worker node may offer, and the images each component runs in.

A worker node's capability is a set of components (SCENEGEMS_WORKER_NODE_COMPONENTS). The vessel stack
components are the campaign layers of the vessel stack matrix, named as LayerRef names them
(asv_system/replay, control_layer/ardupilot, simulation_layer/gazebo, ...); the subsystem
components are design_space_exploration, scene_generation, trajectory_generation, monitoring and calibration.

A job requires components (JobRequirements.components): a simulation every layer of every
vessel's stack, any other job type its subsystem component (JOB_TYPE_COMPONENTS). The images of
the required components are the job's required images, so the release lists the images per
component (cluster/release/roles.py), the deployment tool installs the images of the components
it is given per worker node, and the control node judges a worker node out of date per component.

A stack layer's images are the containers its spec adds to a per-job stack (ContainerSpec.default_image):
every layer runs in a container of its own. An ASV system adds those of the adapters that run it on the
runners' stacks, and a simulation layer adds the simulation subsystem image the simulation runner runs in. A real
vessel has no container of its own: its control layer's images are the MAVProxy and the ArduAgent the simulated
vessels beside it run through, since a real vessel is reached only over its ArduAgent. The
simulation job's runners and the vessel stacks each runs are declared here too (RUNNER_STACKS), so
the Capabilities page can name the runner of a stack without loading the job modules. The registry
is read on first use, so importing this module (the control node does at start) loads neither it nor numpy.
"""

from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Collection, Dict, Iterable, Optional, Set, Tuple

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerImplementationId, LayerRef, Role, SimulationLayerId
from utils.image_names import tagged

if TYPE_CHECKING:
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

# The subsystem images, tagged with SCENEGEMS_IMAGE_TAG (utils/image_names.py)
DESIGN_SPACE_EXPLORATION_IMAGE = tagged("scenegems-design-space-exploration-subsystem")  # the Refinery model generator, built from the pinned Refinery commit
SCENE_GENERATION_IMAGE = tagged("scenegems-scene-generation-subsystem")
TRAJECTORY_GENERATION_IMAGE = tagged("scenegems-trajectory-generation-subsystem")
SIMULATION_IMAGE = tagged("scenegems-simulation-subsystem")
MONITORING_IMAGE = tagged("scenegems-monitoring-subsystem")

ComponentId = str
StackTriple = Tuple[AsvSystemId, ControlLayerId, SimulationLayerId]

# The layers of the vessel stacks jobs run, in catalog order. Campaigns run all but Mission Planner and the layers of a real
# vessel (on_board, real_vessel), which need their operator (an attended job of the workbench).
STACK_LAYERS: Tuple[LayerImplementationId, ...] = (
    AsvSystemId.REPLAY,
    AsvSystemId.USV_NAVIGATION,
    AsvSystemId.MISSION_PLANNER,
    AsvSystemId.ON_BOARD,
    ControlLayerId.NONE,
    ControlLayerId.ARDUPILOT,
    ControlLayerId.CUSTOM,
    ControlLayerId.REAL_VESSEL,
    SimulationLayerId.KINEMATIC,
    SimulationLayerId.ARDUPILOT_SIM,
    SimulationLayerId.GAZEBO,
    SimulationLayerId.REAL_VESSEL,
)
DESIGN_SPACE_EXPLORATION = "design_space_exploration"
SCENE_GENERATION = "scene_generation"
TRAJECTORY_GENERATION = "trajectory_generation"
MONITORING = "monitoring"
CALIBRATION = "calibration"

# The subsystem components and their images: the subsystem a job of the type runs in
SUBSYSTEM_IMAGES: Dict[ComponentId, Tuple[str, ...]] = {
    DESIGN_SPACE_EXPLORATION: (DESIGN_SPACE_EXPLORATION_IMAGE,),
    SCENE_GENERATION: (SCENE_GENERATION_IMAGE,),
    TRAJECTORY_GENERATION: (TRAJECTORY_GENERATION_IMAGE,),
    MONITORING: (MONITORING_IMAGE,),
    CALIBRATION: (SIMULATION_IMAGE,),  # the deviation between repeats runs in a simulation subsystem container
}
# The subsystem component of each job type other than the simulation, whose components come from its vessels' stacks
JOB_TYPE_COMPONENTS: Dict[JobType, ComponentId] = {
    JobType.DESIGN_SPACE_EXPLORATION: DESIGN_SPACE_EXPLORATION,
    JobType.SCENE_GENERATION: SCENE_GENERATION,
    JobType.TRAJECTORY_GENERATION: TRAJECTORY_GENERATION,
    JobType.MONITORING_POST_HOC: MONITORING,
    JobType.CALIBRATION_DEVIATION: CALIBRATION,
}


def layer_component(layer: LayerImplementationId) -> ComponentId:
    """The component of a vessel stack layer: its LayerRef name, such as control_layer/ardupilot."""
    return str(LayerRef.of(layer))


STACK_COMPONENTS: Tuple[ComponentId, ...] = tuple(layer_component(layer) for layer in STACK_LAYERS)
SIMULATION_LAYER_PREFIX = f"{Role.SIMULATION_LAYER.value}/"
COMPONENTS: Tuple[ComponentId, ...] = STACK_COMPONENTS + tuple(SUBSYSTEM_IMAGES)
_ORDER = {component: index for index, component in enumerate(COMPONENTS)}


class SimulationRunner(str, Enum):
    """The runners of the simulation job (cluster/worker_node/jobs/simulation_job.py), the value of its payload's runner."""

    KINEMATIC = "kinematic"  # replay or USV Navigation closed loop, the runner stepping the kinematic simulator's container
    ARDUPILOT = "ardupilot"  # replay or USV Navigation over the lockstep MAVLink adapters on a SITL or Gazebo stack per job
    GAZEBO_CUSTOM = "gazebo_custom"  # replay or USV Navigation on the custom controller, the runner stepping a Gazebo world per job (no SITL)
    ATTENDED = "attended"  # the workbench's setup vessel by vessel, with an operator beside it: it waits for a Start, and Mission Planner may steer a vessel


# The vessel stacks each unattended runner may run. Each must be a campaign stack of the matrix: available and
# not workbench only. The attended runner runs these and the stacks of ATTENDED_STACKS.
RUNNER_STACKS: Dict[SimulationRunner, Tuple[StackTriple, ...]] = {
    SimulationRunner.KINEMATIC: (
        (AsvSystemId.REPLAY, ControlLayerId.NONE, SimulationLayerId.KINEMATIC),
        (AsvSystemId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC),
    ),
    SimulationRunner.ARDUPILOT: (
        (AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),
        (AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO),
        (AsvSystemId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),
        (AsvSystemId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO),
    ),
    SimulationRunner.GAZEBO_CUSTOM: (
        (AsvSystemId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO),
        (AsvSystemId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO),
    ),
}


# The stacks only the attended runner runs: the operator steers the vessel from Mission Planner through MAVProxy,
# or the vessel is a real one, reached through the ArduAgent on board
ATTENDED_STACKS: Tuple[StackTriple, ...] = (
    (AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),
    (AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO),
    (AsvSystemId.REPLAY, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL),
    (AsvSystemId.MISSION_PLANNER, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL),
    (AsvSystemId.ON_BOARD, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL),
)


class UnknownComponent(ValueError):
    """A component id the catalog does not list."""


class JobStackError(ValueError):
    """A runner names a stack the vessel stack matrix does not offer for campaigns."""


def is_component(name: str) -> bool:
    return name in _ORDER


def ordered(components: Iterable[ComponentId]) -> Tuple[ComponentId, ...]:
    """The distinct components in catalog order; an unknown one fails."""
    unique = set(components)
    unknown = sorted(unique - set(_ORDER))
    if unknown:
        raise UnknownComponent(f"unknown component(s) {', '.join(unknown)}; known: {', '.join(COMPONENTS)}")
    return tuple(sorted(unique, key=_ORDER.__getitem__))


def stack_components(stacks: Iterable[StackTriple]) -> Tuple[ComponentId, ...]:
    """Every layer of these vessel stacks as components, in catalog order."""
    return ordered(layer_component(layer) for stack in stacks for layer in stack)


def job_type_of(component: ComponentId) -> JobType:
    """The job type a component serves: the simulation for a vessel stack layer, else its subsystem's."""
    if component in STACK_COMPONENTS:
        return JobType.SIMULATION
    for job_type, subsystem in JOB_TYPE_COMPONENTS.items():
        if subsystem == component:
            return job_type
    raise UnknownComponent(f"unknown component {component!r}")


def _layer_images(layer: LayerImplementationId) -> Tuple[str, ...]:
    from scenegems_tool.vessel_stack.registry.catalog import default_registry

    spec = default_registry().layer(LayerRef.of(layer))
    images = {container.default_image for container in spec.containers} if spec is not None else set()
    role = LayerRef.of(layer).role
    if role == Role.SIMULATION_LAYER:
        images.add(SIMULATION_IMAGE)  # the simulation runner
    elif role == Role.ASV_SYSTEM:
        images.update(_asv_adapter_images(layer))
    if layer is ControlLayerId.REAL_VESSEL:  # by identity: the real vessel's simulation layer has the same value
        images.update(_arduagent_images())
    return tuple(sorted(images))


def _arduagent_images() -> Set[str]:
    """The images of the adapters that run a simulated vessel through ArduAgent, which only an instance with a real vessel selects."""
    from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
    from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER

    return {container.default_image for adapter in (REPLAY_ARDUAGENT_FOLLOWER, MISSION_PLANNER_MAVLINK_PORT) for container in adapter.containers}


def _asv_adapter_images(asv_system: LayerImplementationId) -> Set[str]:
    """The images of the adapters that run an ASV system on the stacks the simulation runners run (the vessel's replay container)."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    resolver = default_resolver()
    images: Set[str] = set()
    for stacks in (*RUNNER_STACKS.values(), ATTENDED_STACKS):
        for software, control_layer, simulation_layer in stacks:
            if software != asv_system:
                continue
            adapter = resolver.resolve(VesselStackConfig(asv_system=software, control_layer=control_layer, simulation_layer=simulation_layer)).asv_adapter
            if adapter is not None:
                images.update(container.default_image for container in adapter.containers)
    return images


@lru_cache(maxsize=1)
def component_images() -> Dict[ComponentId, Tuple[str, ...]]:
    """The images of every component, sorted: a layer's containers (a simulation layer's with the runner), a subsystem's image."""
    images = {layer_component(layer): _layer_images(layer) for layer in STACK_LAYERS}
    images.update(SUBSYSTEM_IMAGES)
    return images


def images_of(components: Collection[ComponentId]) -> Set[str]:
    """The images a worker node or a job needs for these components; components the catalog does not list add none."""
    catalog = component_images()
    return {image for component in components for image in catalog.get(component, ())}


def stack_images(stacks: Iterable[StackTriple]) -> Tuple[str, ...]:
    """The image tags of every container on these stacks' chains, sorted. A stack that is not available, or is workbench only, fails."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    resolver = default_resolver()
    images: Set[str] = set()
    for asv_system, control_layer, simulation_layer in stacks:
        stack = VesselStackConfig(asv_system=asv_system, control_layer=control_layer, simulation_layer=simulation_layer)
        chain = resolver.resolve(stack)
        if not chain.available:
            raise JobStackError(f"({stack}) is not available in the vessel stack matrix: {chain.reason}")
        if chain.capabilities.interactive_only:
            raise JobStackError(f"({stack}) is workbench only, so no job may run it")
        images.update(container.default_image for spec in chain.specs for container in spec.containers)
    return tuple(sorted(images))


def _triple(stack: "VesselStackConfig") -> StackTriple:
    return (stack.asv_system, stack.control_layer, stack.simulation_layer)


def runner_of_stack(stack: "VesselStackConfig") -> Optional[SimulationRunner]:
    """The unattended simulation runner that runs this stack; None when only the attended runner does (a workbench run)."""
    return next((runner for runner, stacks in RUNNER_STACKS.items() if _triple(stack) in stacks), None)


def unrun_campaign_stacks() -> Tuple["VesselStackConfig", ...]:
    """The campaign stacks of the matrix (available, not workbench only) that no simulation runner runs."""
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    return tuple(chain.stack for chain in default_resolver().availability_matrix() if chain.available and not chain.capabilities.interactive_only and runner_of_stack(chain.stack) is None)


def check_runner_stacks() -> None:
    """Raise JobStackError when a runner names a stack the matrix does not offer for campaigns (the release build checks it)."""
    for stacks in RUNNER_STACKS.values():
        stack_images(stacks)
