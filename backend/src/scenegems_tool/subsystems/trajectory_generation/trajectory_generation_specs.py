"""Architecture description of trajectory generation: the generators a request can name and the parts they share.

A new generator is a TrajectoryGeneratorId member plus one GeneratorSpec in generator_specs(); the document, the
page and the coverage check (check_covers_enum) follow. Declared values live here, measured ones in
subsystems/measured_capabilities.yaml under the ids "trajectory_generation/<node id>".
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from scenegems_tool.architecture.architecture_model import (
    GROUP_CAPABILITY,
    GROUP_PARAMETER,
    GROUP_PROPERTY,
    KIND_COMPONENT,
    KIND_INTERFACE,
    KIND_ROLE,
    ROLE_STEP,
    ArchitectureDocument,
    Fact,
    Lane,
    MetamodelEdge,
    MetamodelNode,
)
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, check_covers_enum, spec_edge, spec_node
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGeneratorId

DOCUMENT_ID = "trajectory_generation"
_PACKAGE = "scenegems_tool/subsystems/trajectory_generation"
_CONCRETE = "concrete_level/trajectory_generation"

LANE_ENTRY = "entry"
LANE_GENERATOR = "generator"
LANE_BLOCKS = "building_blocks"


def _id(local: str) -> str:
    return f"{DOCUMENT_ID}/{local}"


META_REQUEST = _id("request")
META_GENERATOR = _id("trajectory_generator")
META_ORACLE = _id("compliance_oracle")
META_ASSEMBLY = _id("trajectory_assembly")
META_SEARCH = _id("search_structure")
META_DISPATCH = _id("request_to_generator")
META_JUDGES = _id("generator_to_oracle")
META_BUILDS = _id("generator_to_assembly")
META_EXPLORES = _id("generator_to_search")

# The building blocks and the metamodel edge by which a generator uses each.
BLOCKS = {
    "colregs_monitor": (META_JUDGES, "judges with"),
    "trajectory_builder": (META_BUILDS, "builds with"),
    "trajectory_tree": (META_EXPLORES, "explores with"),
    "seed_trajectory": (META_EXPLORES, "explores with"),
    "maneuvering_domain": (META_EXPLORES, "explores with"),
}


@dataclass(frozen=True)
class GeneratorSpec:
    generator: TrajectoryGeneratorId
    label: str
    description: str
    code: str
    uses: Tuple[str, ...]  # keys of BLOCKS
    randomness: str
    parameters: Tuple[Fact, ...] = ()


def _planner_parameters() -> Tuple[Fact, ...]:
    from concrete_level.trajectory_generation.monitor_guided_planner import MonitorGuidedPlanner as Search
    from concrete_level.trajectory_generation.trajectory_generator import TIME_STEP

    def parameter(key: str, label: str, value, unit: Optional[str] = None) -> Fact:
        return Fact(key, label, value, GROUP_PARAMETER, unit=unit)

    return (
        parameter("timeStep", "Time step", TIME_STEP, "s"),
        parameter("bestRandomNodesK", "Leaves expanded per round", Search.BEST_RANDOM_NODES_K),
    )


def generator_specs() -> Tuple[GeneratorSpec, ...]:
    return (
        GeneratorSpec(
            TrajectoryGeneratorId.MONITOR_DRIVEN_RRT,
            "Monitor-guided planner",
            "Follows a maneuvering corridor for every give-way vessel and repairs each step the COLREGS monitor fails with a short tree search over sampled heading changes. The monitor judges every step in process, so the path it returns keeps the rules satisfied.",
            f"{_CONCRETE}/monitor_guided_planner.py",
            ("colregs_monitor", "trajectory_builder", "trajectory_tree", "seed_trajectory", "maneuvering_domain"),
            "seeded (random, numpy)",
            _planner_parameters(),
        ),
        GeneratorSpec(
            TrajectoryGeneratorId.STRAIGHT,
            "Straight",
            "Every vessel keeps its initial course and speed up to a timespan. It searches nothing and returns at once.",
            f"{_PACKAGE}/straight_trajectory_generator.py",
            ("trajectory_builder",),
            "none",
        ),
    )


def _metamodel() -> Tuple[Tuple[MetamodelNode, ...], Tuple[MetamodelEdge, ...]]:
    nodes = (
        MetamodelNode(
            META_REQUEST,
            LANE_ENTRY,
            "Generation request",
            "How a request reaches a generator: the initial concrete scene, the COLREGS constraints and the TrajectoryGenerationParams, answered by TrajectoryData.",
            KIND_ROLE,
            ("initial concrete scene", "COLREGS constraints", "TrajectoryGenerationParams (generator, timeStep, timeout, seed, ...)", "reply: TrajectoryData and preview chunks"),
            "Add a delivery path that builds TrajectoryGenerationParams and hands them to the worker.",
            f"{_PACKAGE}/trajectory_generation_types.py",
        ),
        MetamodelNode(
            META_GENERATOR,
            LANE_GENERATOR,
            "Trajectory generator",
            "Produces the trajectories of every vessel for one initial scene. The request names it by id.",
            KIND_INTERFACE,
            (
                "id: a TrajectoryGeneratorId member",
                "run(initial scene, time step, timespan, seed) returns TrajectoryData",
                "observer: preview callback (Trajectories, MonitoredTrajectory, iteration), optional",
                "termination_signal: stop early and return the best path so far, optional",
            ),
            "Add a TrajectoryGeneratorId member, a GeneratorSpec in trajectory_generation_specs.py and a branch in trajectory_generation_worker.py.",
            f"{_PACKAGE}/trajectory_generation_worker.py",
        ),
        MetamodelNode(
            META_ORACLE,
            LANE_BLOCKS,
            "Compliance oracle",
            "Judges a scene against the COLREGS while a generator builds a path. Shared with the monitoring subsystem.",
            KIND_INTERFACE,
            ("step(current monitored scene, next scene, time step) returns the monitored scene with its rule results",),
            "Hand the search another oracle with the same step contract.",
            "concrete_level/colregs_monitoring/colregs_monitor.py",
        ),
        MetamodelNode(
            META_ASSEMBLY,
            LANE_BLOCKS,
            "Trajectory assembly",
            "Builds and extends trajectories scene by scene.",
            KIND_COMPONENT,
            ("default trajectory from a scene", "simulate to length", "merge trajectories"),
            None,
            f"{_CONCRETE}/trajectory_builder.py",
        ),
        MetamodelNode(
            META_SEARCH,
            LANE_BLOCKS,
            "Search structure",
            "What a search generator keeps while it explores: scene nodes, objectives, seed paths and the domain a give-way vessel is held to.",
            KIND_COMPONENT,
            ("scene nodes with a parent link", "objectives per vessel", "repair window"),
            None,
            f"{_CONCRETE}/trajectory_tree_builder.py",
        ),
    )
    edges = (
        MetamodelEdge(
            META_DISPATCH,
            META_REQUEST,
            META_GENERATOR,
            "dispatch by id",
            "The worker picks the generator the request names.",
            "adapter",
            ("TrajectoryGeneratorId", "TrajectoryDataFactory"),
            None,
            f"{_PACKAGE}/trajectory_generation_worker.py",
        ),
        MetamodelEdge(META_JUDGES, META_GENERATOR, META_ORACLE, "judges with", "A generator that must keep the rules calls the oracle on every candidate scene.", "uses"),
        MetamodelEdge(META_BUILDS, META_GENERATOR, META_ASSEMBLY, "builds with", "Every generator assembles its result as Trajectories.", "uses"),
        MetamodelEdge(META_EXPLORES, META_GENERATOR, META_SEARCH, "explores with", "Search generators keep their state in a search structure.", "uses"),
    )
    return nodes, edges


def trajectory_generation_document(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> ArchitectureDocument:
    generators = generator_specs()
    check_covers_enum(TrajectoryGeneratorId, (spec.generator.value for spec in generators), "trajectory generation")
    metamodel_nodes, metamodel_edges = _metamodel()

    def node(local, lane, label, description, implements, code, tags=(), extra=()):
        facts = (Fact("code", "Code", code, GROUP_PROPERTY), *extra)
        return spec_node(DOCUMENT_ID, local, lane, label, description, implements, facts=facts, tags=tags, measurements=measurements)

    entries = ("cluster_job", "workbench_service")
    nodes = [
        node(
            "cluster_job",
            LANE_ENTRY,
            "Cluster job",
            "The trajectory_generation job: dispatched to a worker node's trajectory generation pool, which queues requests for its workers (one per slot).",
            META_REQUEST,
            "scenegems_tool/cluster/worker_node/jobs/trajectory_generation_job.py",
            ("cluster",),
        ),
        node(
            "workbench_service",
            LANE_ENTRY,
            "Workbench service",
            "The MQTT service of the workbench: one worker, one request at a time, with live previews of the search.",
            META_REQUEST,
            f"{_PACKAGE}/trajectory_generation_service_main.py",
            ("workbench",),
        ),
    ]
    edges = []
    for spec in generators:
        nodes.append(
            node(
                spec.generator.value,
                LANE_GENERATOR,
                spec.label,
                spec.description,
                META_GENERATOR,
                spec.code,
                extra=(Fact("randomness", "Randomness", spec.randomness, GROUP_CAPABILITY), *spec.parameters),
            )
        )
        edges.extend(spec_edge(DOCUMENT_ID, entry, spec.generator.value, "dispatch by id", META_DISPATCH, measurements=measurements) for entry in entries)
        edges.extend(spec_edge(DOCUMENT_ID, spec.generator.value, block, BLOCKS[block][1], BLOCKS[block][0], kind="uses", measurements=measurements) for block in spec.uses)
    nodes.extend(
        (
            node(
                "colregs_monitor",
                LANE_BLOCKS,
                "COLREGS monitor",
                "The rule engine, run in process. The monitoring subsystem runs the same engine.",
                META_ORACLE,
                "concrete_level/colregs_monitoring/colregs_monitor.py",
                ("shared",),
            ),
            node("trajectory_builder", LANE_BLOCKS, "Trajectory builder", "Default trajectories from a scene, extension by simulation, merging.", META_ASSEMBLY, f"{_CONCRETE}/trajectory_builder.py"),
            node("trajectory_tree", LANE_BLOCKS, "Trajectory tree", "Scene nodes and per-vessel objectives of the search.", META_SEARCH, f"{_CONCRETE}/trajectory_tree_builder.py"),
            node(
                "seed_trajectory",
                LANE_BLOCKS,
                "Seed trajectory",
                "A seed path in phases (outbound, parallel, inbound, after) that the search repairs in windows.",
                META_SEARCH,
                f"{_CONCRETE}/seed_trajectory.py",
            ),
            node("maneuvering_domain", LANE_BLOCKS, "Maneuvering domain", "The give-way trapezoid grown from frozen potential collision domains.", META_SEARCH, f"{_CONCRETE}/maneuvering_domain.py"),
        )
    )
    return ArchitectureDocument(
        id=DOCUMENT_ID,
        title="Trajectory generation",
        summary="Generators that turn an initial scene into trajectories for every vessel, the entry points that reach them and the blocks they run on.",
        lanes=(
            Lane(LANE_ENTRY, "Entry point", "How a request arrives."),
            Lane(LANE_GENERATOR, "Generator", "The algorithm that plans the trajectories."),
            Lane(LANE_BLOCKS, "Building blocks", "Parts the generators share."),
        ),
        metamodel_nodes=metamodel_nodes,
        metamodel_edges=metamodel_edges,
        nodes=tuple(nodes),
        edges=tuple(edges),
        role=ROLE_STEP,
        step="Trajectory generation",
        takes="a scene",
        gives="trajectories",
        job_types=("trajectory_generation",),
    ).validate()
