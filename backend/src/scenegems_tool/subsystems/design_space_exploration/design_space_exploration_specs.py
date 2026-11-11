"""Architecture description of the design space exploration: the first step of the chain.

What a design_space_exploration job runs: the specification and the scope make one Refinery problem, an
explore-design-space request to the worker node's design space exploration subsystem becomes one task of its pool,
the task runs the Refinery model generator, which enumerates the problem's models, and every model comes back as the
source of a functional equivalence class (FEC). A new scenario family is another specification text; a new generator
adds one entry to the tuples below and a program that speaks the job folder protocol.

The names and numbers are literals so that describing the subsystem imports neither the job modules nor Docker; the
test test_design_space_exploration_specs.py checks them against the code.
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

DOCUMENT_ID = "design_space_exploration"
_PACKAGE = "scenegems_tool/subsystems/design_space_exploration"

LANE_ENTRY = "entry"
LANE_PROBLEM = "problem"
LANE_EXPLORATION = "exploration"
LANE_OUTPUT = "output"

# Checked against the code by the test
JOB_TYPE = "design_space_exploration"
IMAGE_REPOSITORY = "scenegems-design-space-exploration-subsystem"
GENERATOR_COMMAND = "generate-models job -folder <task folder>"
REQUEST = "explore-design-space"
DEFAULT_SCOPE = "TS = 2, StaticObstacle = 0"
DEFAULT_TIMEOUT_S = 600
DEFAULT_MAX_FECS = 1000
UPSTREAM = "github.com/fdominik98/refinery, folder scenegems/"


def _id(local: str) -> str:
    return f"{DOCUMENT_ID}/{local}"


META_REQUEST = _id("request")
META_SPECIFICATION = _id("specification_text")
META_SCOPE = _id("scope")
META_GENERATOR = _id("model_generator")
META_FECS = _id("fecs")


@dataclass(frozen=True)
class Part:
    local: str
    lane: str
    label: str
    description: str
    implements: str
    code: str
    facts: Tuple[Fact, ...] = ()
    tags: Tuple[str, ...] = ()


def parts() -> Tuple[Part, ...]:
    return (
        Part(
            "request",
            LANE_ENTRY,
            "Request",
            "An explore-design-space request over the message broker, sent by the worker node's daemon for a design_space_exploration job it leased. The subsystem is one long-lived "
            "container per worker node: the request becomes one task, which waits in the queue and then runs in a worker process of the pool. "
            "A workbench run and a campaign's first step both queue this job.",
            META_REQUEST,
            "scenegems_tool/messaging/mqtt_design_space_exploration_service.py",
            (
                *pool_facts(
                    REQUEST,
                    "one per request: the whole exploration, which cannot be split. Different requests run side by side",
                    "the request's seed is the generator's random seed and fixes the order the FECs are found in; a job that names none uses 1",
                    "sensor/design_space: the explored FECs, or why the generator could not explore; exec/feedback: the generator's progress, a line a second; exec/response: every task state",
                ),
                Fact("max_fecs", "FEC cap", DEFAULT_MAX_FECS, GROUP_PARAMETER, note="a campaign's default; without a cap every FEC is generated"),
                Fact("timeout", "Time limit", DEFAULT_TIMEOUT_S, GROUP_PARAMETER, unit="s", note="the FECs found until then are kept"),
            ),
            ("cluster",),
        ),
        Part(
            "colregs_specification",
            LANE_PROBLEM,
            "COLREGS specification",
            "The default specification: the vessel types, the own ship, the target ships and the static obstacles, the encounter relations between them (head-on, crossing, overtaking) "
            "and the constraints a consistent encounter obeys. It is the first part of every FEC specification of the catalog, with the own ship fixed.",
            META_SPECIFICATION,
            "backend/assets/design_space/default_specification.problem",
            (Fact("own_ship", "Own ship", "fixed: one, type OSPassengerShip", GROUP_PROPERTY, note="without it every FEC would come once per vessel type"),),
        ),
        Part(
            "scope_bounds",
            LANE_PROBLEM,
            "Scope bounds",
            "How many target ships and static obstacles a FEC has: a count or a range per class. Every upper bound is finite, so the exploration ends.",
            META_SCOPE,
            f"{_PACKAGE}/design_space.py",
            (Fact("default", "Default", DEFAULT_SCOPE, GROUP_PARAMETER), Fact("syntax", "Syntax", "<class> = <count> or <class> = <lower>..<upper>, comma separated", GROUP_PROPERTY)),
        ),
        Part(
            "refinery",
            LANE_EXPLORATION,
            "Refinery model generator",
            "Explores the refinements of the partial model: every decision adds a fact (a type, a relation, an instance the scope allows), and a state that satisfies every constraint is a model. "
            "Without a cap it stops when no state is left, so the result is every FEC of the specification within the scope.",
            META_GENERATOR,
            UPSTREAM,
            (
                Fact("image", "Image", IMAGE_REPOSITORY, GROUP_PROPERTY),
                Fact("command", "Command", GENERATOR_COMMAND, GROUP_PROPERTY),
                Fact("distinct", "Distinct", "up to isomorphism", GROUP_CAPABILITY, note="by a 32 bit hash of the objects' neighborhoods (state coder depth 7), not a full isomorphism check"),
                Fact("randomness", "Randomness", "seeded: one seed fixes the order the FECs are found in", GROUP_CAPABILITY),
                Fact("partial", "Partial result", "the FECs found until the cap, the time limit or a stop", GROUP_CAPABILITY),
                Fact("streaming", "Progress", "one status line per second with the FECs found so far", GROUP_CAPABILITY),
                Fact("process", "Runs as", "a process of its own per task, in a folder of its own, ended when the task is cancelled", GROUP_PROPERTY),
            ),
        ),
        Part(
            "fec_sources",
            LANE_OUTPUT,
            "FEC sources",
            "Every model as Refinery source: the metamodel and the constraints as given, followed by the model's instances and relations, which the functional model parser of the scene generation reads. "
            "Each is stored as a functional scenario artifact; in a campaign each becomes a FEC explored/<index> whose cases start at scene generation.",
            META_FECS,
            "scenegems_tool/assurance/pipeline/case_machine.py",
        ),
    )


# (source local id, target local id, metamodel edge, label)
_FLOW = (
    ("request", "colregs_specification", "request_to_specification", "specification text"),
    ("request", "scope_bounds", "request_to_scope", "scope"),
    ("colregs_specification", "refinery", "specification_to_generator", "problem"),
    ("scope_bounds", "refinery", "scope_to_generator", "scope entries"),
    ("refinery", "fec_sources", "generator_to_fecs", "model sources"),
)


def _metamodel() -> Tuple[Tuple[MetamodelNode, ...], Tuple[MetamodelEdge, ...]]:
    nodes = (
        MetamodelNode(
            META_REQUEST,
            LANE_ENTRY,
            "Exploration request",
            "A specification, a scope, a cap on the number of FECs, a time limit and a seed. The reply lists the FECs found and says whether they are the whole design space.",
            KIND_ROLE,
            ("problem: the specification text", "scopes: the scope's entries", "max_models, timeout_s, random_seed", "reply: stop_reason, complete, fecs, functional_scenarios"),
            "Add a delivery path that submits a design_space_exploration job, or send the subsystem an explore-design-space request.",
            "scenegems_tool/cluster/worker_node/jobs/design_space_exploration_job.py",
        ),
        MetamodelNode(
            META_SPECIFICATION,
            LANE_PROBLEM,
            "Specification",
            "The metamodel and the well-formedness constraints of a scenario family, and whatever the family fixes.",
            KIND_INTERFACE,
            ("enums and classes with their relations", "predicates", "error predicates: the well-formedness constraints", "assertions that fix part of every model"),
            "Another scenario family is another specification text; its models must declare the instances and relations the functional model parser reads.",
            "backend/assets/design_space/default_specification.problem",
        ),
        MetamodelNode(
            META_SCOPE,
            LANE_PROBLEM,
            "Scope",
            "The number of instances of a class in every model.",
            KIND_INTERFACE,
            ("<class> = <count>", "<class> = <lower>..<upper>", "parse_scope(text) returns the generator's entries"),
            None,
            f"{_PACKAGE}/design_space.py",
        ),
        MetamodelNode(
            META_GENERATOR,
            LANE_EXPLORATION,
            "Model generator",
            "Enumerates the models of the problem within the scope, each once.",
            KIND_INTERFACE,
            (
                "reads job.json of its task's folder: the request as its payload",
                "writes scenegems-status lines: message and progress",
                "writes result.json into the folder: stop_reason, complete and each model's source",
                "runs as a child process of the task's worker, without the broker",
            ),
            "Another generator is a program in the subsystem's image that speaks the job folder protocol (cluster/worker_node/launchers/per_job/job_container_io.py) and returns each model's source.",
            "scenegems_tool/subsystems/design_space_exploration/design_space_exploration_worker.py",
        ),
        MetamodelNode(
            META_FECS,
            LANE_OUTPUT,
            "FECs",
            "The functional equivalence classes found: one functional scenario each.",
            KIND_COMPONENT,
            ("functional_scenarios: one .problem text per FEC", "fecs: index, vessel count and obstacle count per FEC"),
            None,
            "scenegems_tool/subsystems/design_space_exploration/design_space.py",
        ),
    )
    edges = (
        MetamodelEdge(_id("request_to_specification"), META_REQUEST, META_SPECIFICATION, "specification text", "The request carries the specification as text.", "data"),
        MetamodelEdge(_id("request_to_scope"), META_REQUEST, META_SCOPE, "scope", "", "data"),
        MetamodelEdge(_id("specification_to_generator"), META_SPECIFICATION, META_GENERATOR, "problem", "", "data"),
        MetamodelEdge(_id("scope_to_generator"), META_SCOPE, META_GENERATOR, "scope entries", "", "data"),
        MetamodelEdge(_id("generator_to_fecs"), META_GENERATOR, META_FECS, "model sources", "", "data"),
    )
    return nodes, edges


def design_space_exploration_document(measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> ArchitectureDocument:
    metamodel_nodes, metamodel_edges = _metamodel()
    nodes = [
        spec_node(
            DOCUMENT_ID,
            part.local,
            part.lane,
            part.label,
            part.description,
            part.implements,
            facts=(Fact("code", "Code", part.code, GROUP_PROPERTY), *part.facts),
            tags=part.tags,
            measurements=measurements,
        )
        for part in parts()
    ]
    edges = [spec_edge(DOCUMENT_ID, source, target, label, _id(meta), kind="data", measurements=measurements) for source, target, meta, label in _FLOW]
    return ArchitectureDocument(
        id=DOCUMENT_ID,
        title="Design space exploration",
        summary="Finds every functional equivalence class (FEC) of a specification within a scope: the scenario classes the rest of the chain turns into scenes, trajectories and runs.",
        lanes=(
            Lane(LANE_ENTRY, "Entry point", "How a request arrives."),
            Lane(LANE_PROBLEM, "Problem", "What is explored: the specification and the scope."),
            Lane(LANE_EXPLORATION, "Exploration", "The search for every model."),
            Lane(LANE_OUTPUT, "Output", "The FECs found."),
        ),
        metamodel_nodes=metamodel_nodes,
        metamodel_edges=metamodel_edges,
        nodes=tuple(nodes),
        edges=tuple(edges),
        notes=(
            "The FEC catalog of the control node (backend/assets/generated_functional_models/all) holds the FECs of the default specification for the scopes it was generated with; "
            "an exploration with the same scope finds the same classes.",
            "Attribute values are not enumerated, and two models that differ only in the names of their objects count once.",
        ),
        role=ROLE_STEP,
        step="Design space exploration",
        takes="a specification and a scope",
        gives="FECs",
        job_types=(JOB_TYPE,),
    ).validate()
