"""Architecture description of scene generation: the pipeline the live scene generation subsystem runs.

Only what the running subsystem and the cluster job execute is described: scene_generation_worker.py fixes one
pipeline (functional model parser, logical scenario builder with the uniform instance initializer, the all
aggregate and two-step collision-domain rejection sampling). The other solvers under logical_level/ belong to the
offline evaluation scripts and are not shown. A new live implementation adds one entry to the tuples below.

The ids and names are literals so that describing the subsystem does not import Scenic; the test
test_scene_generation_specs.py checks them against the code.
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
from scenegems_tool.subsystems.subsystem_spec import MeasuredFacts, pool_facts, spec_edge, spec_node

DOCUMENT_ID = "scene_generation"
_PACKAGE = "scenegems_tool/subsystems/scene_generation"

LANE_ENTRY = "entry"
LANE_MODEL = "model"
LANE_PROBLEM = "problem"
LANE_SOLVER = "solver"
LANE_OUTPUT = "output"

# Names the worker passes; checked against the code by the test.
CONFIG_GROUP = "rs-msr"
INITIALIZER_NAME = "uniform"
AGGREGATE_NAME = "all"
SOLVER_ALGORITHM = "Two_Step_CD_Rejection_Sampling"


def _id(local: str) -> str:
    return f"{DOCUMENT_ID}/{local}"


META_REQUEST = _id("request")
META_PARSER = _id("functional_model_parser")
META_BUILDER = _id("logical_scenario_builder")
META_INITIALIZER = _id("instance_initializer")
META_AGGREGATE = _id("aggregate")
META_SOLVER = _id("solver")
META_SCENE_BUILDER = _id("scene_builder")


@dataclass(frozen=True)
class Stage:
    local: str
    lane: str
    label: str
    description: str
    implements: str
    code: str
    facts: Tuple[Fact, ...] = ()


def stages() -> Tuple[Stage, ...]:
    return (
        Stage(
            "parser",
            LANE_MODEL,
            "Model parser",
            "Parses the .problem text of a functional scenario into a FunctionalScenario: vessels, obstacles and the relations that must hold between them.",
            META_PARSER,
            "functional_level/models/model_parser.py",
        ),
        Stage(
            "builder",
            LANE_MODEL,
            "Logical scenario builder",
            "Maps the functional scenario to a logical one: one actor variable per vessel and obstacle, typed by the vessel and obstacle type tables and constrained by the COLREGS constants.",
            META_BUILDER,
            "logical_level/mapping/logical_scenario_builder.py",
        ),
        Stage(
            "uniform_initializer",
            LANE_PROBLEM,
            "Uniform initializer",
            "Draws the starting population uniformly inside the bounds of every actor variable.",
            META_INITIALIZER,
            "logical_level/mapping/instance_initializer.py",
            (Fact("name", "Name", INITIALIZER_NAME, GROUP_PROPERTY), Fact("population", "Population", 1, GROUP_PARAMETER)),
        ),
        Stage(
            "aggregate_all",
            LANE_PROBLEM,
            "Aggregate all",
            "Adds the penalties of every actor into one value, so a scene is valid when the penalty index is 0.",
            META_AGGREGATE,
            "logical_level/constraint_satisfaction/aggregates.py",
            (Fact("name", "Name", AGGREGATE_NAME, GROUP_PROPERTY),),
        ),
        Stage(
            "two_step_cd_rejection_sampling",
            LANE_SOLVER,
            "Two-step CD rejection sampling",
            "Rejection sampling in two steps: region maps from the collision-domain geometry of each encounter (head-on, crossing, overtaking sectors and visibility distances) restrict where the vessels are drawn, then Scenic samples inside them until the constraints hold or the timeout ends the search.",
            META_SOLVER,
            "logical_level/constraint_satisfaction/rejection_sampling/rejection_sampling_pipeline.py",
            (
                Fact("algorithm", "Algorithm", SOLVER_ALGORITHM, GROUP_PROPERTY),
                Fact("config_group", "Config group", CONFIG_GROUP, GROUP_PROPERTY),
                Fact("randomness", "Randomness", "seeded: one seed fixes the scene (random, numpy, Scenic)", GROUP_CAPABILITY),
                Fact("streaming", "Streaming", "publishes its best sample at most once per second", GROUP_CAPABILITY),
            ),
        ),
        Stage(
            "scene_builder",
            LANE_OUTPUT,
            "Scene builder",
            "Turns the solution's assignments into a ConcreteScene (position, heading and speed per actor).",
            META_SCENE_BUILDER,
            "concrete_level/trajectory_generation/scene_builder.py",
        ),
    )


# (source local id, target local id, metamodel edge, label) of the pipeline between the stages.
_FLOW = (
    ("parser", "builder", "parser_to_builder", "functional scenario"),
    ("builder", "uniform_initializer", "builder_to_initializer", "actor variables"),
    ("builder", "aggregate_all", "builder_to_aggregate", "logical scenario"),
    ("uniform_initializer", "two_step_cd_rejection_sampling", "initializer_to_solver", "population"),
    ("aggregate_all", "two_step_cd_rejection_sampling", "aggregate_to_solver", "penalty"),
    ("two_step_cd_rejection_sampling", "scene_builder", "solver_to_scene_builder", "assignments"),
)


def _metamodel() -> Tuple[Tuple[MetamodelNode, ...], Tuple[MetamodelEdge, ...]]:
    nodes = (
        MetamodelNode(
            META_REQUEST,
            LANE_ENTRY,
            "Generation request",
            "A functional scenario, the domain tables (vessel types, obstacle types, COLREGS constants), a timeout and an optional seed. The reply streams concrete scenes and marks the last one final.",
            KIND_ROLE,
            ("functional scenario text", "vessel type, obstacle type and COLREGS tables", "timeout, seed, enforce_low_tcpa", "reply: EvaluationData with best_scene and valid"),
            "Add a delivery path that builds an MqttSceneGenerationTask.",
            f"{_PACKAGE}/scene_generation_types.py",
        ),
        MetamodelNode(
            META_PARSER,
            LANE_MODEL,
            "Functional model parser",
            "Reads the functional description of a scenario.",
            KIND_INTERFACE,
            ("parse_problem(text) returns a FunctionalScenario",),
            "Another notation needs a parser that returns the same FunctionalScenario.",
            "functional_level/models/model_parser.py",
        ),
        MetamodelNode(
            META_BUILDER,
            LANE_MODEL,
            "Logical scenario builder",
            "Derives the search problem (actor variables and constraints) from the functional scenario.",
            KIND_COMPONENT,
            ("build_from_functional(functional, vessel types, obstacle types, COLREGS constants, initializer name) returns a LogicalScenario",),
            None,
            "logical_level/mapping/logical_scenario_builder.py",
        ),
        MetamodelNode(
            META_INITIALIZER,
            LANE_PROBLEM,
            "Instance initializer",
            "Produces the starting population of a solver.",
            KIND_INTERFACE,
            ("name", "_do_get_population() returns one individual", "get_population(size)"),
            "Subclass InstanceInitializer and select it by name in the worker.",
            "logical_level/mapping/instance_initializer.py",
        ),
        MetamodelNode(
            META_AGGREGATE,
            LANE_PROBLEM,
            "Aggregate",
            "Reduces the penalties of a candidate to the objective the solver minimizes.",
            KIND_INTERFACE,
            ("name", "evaluate(individual) returns the objective", "derive_penalty(individual)"),
            "Subclass Aggregate and register its name for Aggregate.factory.",
            "logical_level/constraint_satisfaction/aggregates.py",
        ),
        MetamodelNode(
            META_SOLVER,
            LANE_SOLVER,
            "Solver",
            "Searches for an assignment with no penalty.",
            KIND_INTERFACE,
            (
                "init_problem(...)",
                "evaluate(input, eval data) returns the best solution, generations and runtime",
                "convert_results(...)",
                "algorithm_desc()",
                "observer and termination_signal callbacks",
            ),
            "Subclass CSPSolver and wire it into scene_generation_worker.py.",
            "logical_level/constraint_satisfaction/csp_evaluation/csp_solver.py",
        ),
        MetamodelNode(
            META_SCENE_BUILDER,
            LANE_OUTPUT,
            "Scene builder",
            "Builds the concrete scene a solution describes.",
            KIND_COMPONENT,
            ("build_from_assignments(assignments) returns a ConcreteScene",),
            None,
            "concrete_level/trajectory_generation/scene_builder.py",
        ),
    )
    edges = (
        MetamodelEdge(_id("request_to_parser"), META_REQUEST, META_PARSER, "functional text", "The request carries the functional scenario text.", "data"),
        MetamodelEdge(_id("parser_to_builder"), META_PARSER, META_BUILDER, "functional scenario", "", "data"),
        MetamodelEdge(_id("builder_to_initializer"), META_BUILDER, META_INITIALIZER, "actor variables", "", "data"),
        MetamodelEdge(_id("builder_to_aggregate"), META_BUILDER, META_AGGREGATE, "logical scenario", "", "data"),
        MetamodelEdge(_id("initializer_to_solver"), META_INITIALIZER, META_SOLVER, "population", "", "data"),
        MetamodelEdge(_id("aggregate_to_solver"), META_AGGREGATE, META_SOLVER, "penalty", "", "data"),
        MetamodelEdge(_id("solver_to_scene_builder"), META_SOLVER, META_SCENE_BUILDER, "assignments", "", "data"),
    )
    return nodes, edges


def scene_generation_document(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> ArchitectureDocument:
    metamodel_nodes, metamodel_edges = _metamodel()
    entries = (
        (
            "request",
            "Request",
            "A generate-scene request over the message broker, sent by the worker node's daemon for a job it leased. The subsystem is one long-lived container per worker node: "
            "the request becomes one task, which waits in the queue and then runs in a worker process of the pool.",
            "scenegems_tool/messaging/mqtt_scene_generation_service.py",
            "cluster",
        ),
    )
    pool = pool_facts(
        "generate-scene",
        "one per request: the search for one scene",
        "the request's seed fixes every random draw of the search, so the same request gives the same scene; a request without one gets a seed drawn",
        "sensor/generated_scene: the best scene so far once a second, then the final one; exec/response: every task state",
    )
    nodes = [
        spec_node(DOCUMENT_ID, local, LANE_ENTRY, label, description, META_REQUEST, facts=(Fact("code", "Code", code, GROUP_PROPERTY), *pool), tags=(tag,), measurements=measurements)
        for local, label, description, code, tag in entries
    ]
    for stage in stages():
        nodes.append(
            spec_node(
                DOCUMENT_ID,
                stage.local,
                stage.lane,
                stage.label,
                stage.description,
                stage.implements,
                facts=(Fact("code", "Code", stage.code, GROUP_PROPERTY), *stage.facts),
                measurements=measurements,
            )
        )
    edges = [spec_edge(DOCUMENT_ID, local, "parser", "functional text", _id("request_to_parser"), kind="data", measurements=measurements) for local, *_ in entries]
    edges.extend(spec_edge(DOCUMENT_ID, source, target, label, _id(meta), kind="data", measurements=measurements) for source, target, meta, label in _FLOW)
    return ArchitectureDocument(
        id=DOCUMENT_ID,
        title="Scene generation",
        summary="The pipeline that turns a functional scenario into one concrete scene: a request becomes one task of the subsystem's pool, and the task runs the pipeline.",
        lanes=(
            Lane(LANE_ENTRY, "Entry point", "How a request arrives."),
            Lane(LANE_MODEL, "Scenario model", "From the functional text to the logical search problem."),
            Lane(LANE_PROBLEM, "Search problem", "The starting population and the objective."),
            Lane(LANE_SOLVER, "Solver", "The search for a scene without penalty."),
            Lane(LANE_OUTPUT, "Output", "The concrete scene."),
        ),
        metamodel_nodes=metamodel_nodes,
        metamodel_edges=metamodel_edges,
        nodes=tuple(nodes),
        edges=tuple(edges),
        notes=("Only the implementations the live subsystem runs are listed. The evolutionary solvers and the other rejection samplers under logical_level/ serve the offline evaluation scripts.",),
        role=ROLE_STEP,
        step="Scene generation",
        takes="a FEC",
        gives="a scene",
        job_types=("scene_generation",),
    ).validate()
