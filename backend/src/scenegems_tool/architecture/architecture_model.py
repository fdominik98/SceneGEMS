"""The architecture description: one document per part of the system, drawn by the web console's Capabilities page.

A document has two graphs over the same lanes (the stages of the part, left to right):

    metamodel       the generic nodes (interfaces, roles) and edges (generic adapters) an implementation has to fill in
    nodes / edges   the concrete implementations and the adapters between them, each pointing at the metamodel entry
                    it implements (`implements`)

Every node and edge carries facts: declared values (what the spec states), measured values (what a measurement
produced, with its evidence) and properties. Documents are built from the specs in code, written to
backend/assets/architecture at master startup (architecture_files.py) and served by the operator API. Measured
values are never written here: they come from the measured capability files and are merged in when a document is built.
"""

import enum
import math
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

SCHEMA_VERSION = 2  # 2: a document says its place in the chain (role, step, takes, gives, job_types)

FactValue = Union[str, float, int, bool, None]

GROUP_CAPABILITY = "capability"  # what the part can do (repeatability, speedup, environment support)
GROUP_PARAMETER = "parameter"  # a setting it takes, with the default as value
GROUP_PROPERTY = "property"  # anything else worth knowing (code location, entry point, order)

STATUS_AVAILABLE = "available"
STATUS_PLANNED = "planned"

KIND_ROLE = "role"  # a lane's generic layer: what every implementation of the lane has to be
KIND_INTERFACE = "interface"
KIND_COMPONENT = "component"

ROLE_STEP = "step"  # the part performs one step of the chain
ROLE_SUPPORT = "support"  # the part serves the steps (monitoring judges their outputs)

UNBOUNDED = "unbounded"  # the display value of a limit that is infinity


@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    value: FactValue
    group: str = GROUP_PROPERTY
    measured: bool = False  # the value comes from a measurement, not from a declaration
    unit: Optional[str] = None
    note: Optional[str] = None  # why the value is what it is, or what the measurement covers


@dataclass(frozen=True)
class Lane:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class MetamodelNode:
    id: str
    lane: str
    label: str
    description: str
    kind: str = KIND_INTERFACE
    members: Tuple[str, ...] = ()  # what an implementation has to provide: methods, ports, spec fields
    extension: Optional[str] = None  # how to add an implementation
    code: Optional[str] = None  # where the contract is defined


@dataclass(frozen=True)
class MetamodelEdge:
    id: str
    source: str
    target: str
    label: str
    description: str
    kind: str = "adapter"  # adapter | uses | data
    members: Tuple[str, ...] = ()
    extension: Optional[str] = None
    code: Optional[str] = None


@dataclass(frozen=True)
class ArchitectureNode:
    id: str
    lane: str
    label: str
    description: str
    implements: Optional[str] = None  # id of the metamodel node
    status: str = STATUS_AVAILABLE
    facts: Tuple[Fact, ...] = ()
    ports_provided: Tuple[str, ...] = ()
    ports_required: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    evidence: str = ""  # how the measured facts were obtained


@dataclass(frozen=True)
class ArchitectureEdge:
    id: str
    source: str
    target: str
    label: str
    description: str
    implements: Optional[str] = None  # id of the metamodel edge
    kind: str = "adapter"
    status: str = STATUS_AVAILABLE
    default: bool = True  # the adapter the resolver takes unless a vessel names another
    facts: Tuple[Fact, ...] = ()
    ports_provided: Tuple[str, ...] = ()
    ports_required: Tuple[str, ...] = ()
    tags: Tuple[str, ...] = ()
    evidence: str = ""


@dataclass(frozen=True)
class UnsupportedLink:
    """A connection the design rules out, with the reason."""

    source: str
    target: str
    reason: str


@dataclass(frozen=True)
class Combination:
    """One path through the lanes (one node per lane) and what the resolver says about it."""

    path: Tuple[str, ...]  # node ids, one per lane
    status: str  # available | planned | unavailable
    reasons: Tuple[str, ...] = ()
    facts: Tuple[Fact, ...] = ()  # the weakest link over the path


@dataclass(frozen=True)
class ArchitectureDocument:
    id: str
    title: str
    summary: str
    lanes: Tuple[Lane, ...]
    metamodel_nodes: Tuple[MetamodelNode, ...]
    metamodel_edges: Tuple[MetamodelEdge, ...]
    nodes: Tuple[ArchitectureNode, ...]
    edges: Tuple[ArchitectureEdge, ...]
    unsupported: Tuple[UnsupportedLink, ...] = ()
    combinations: Tuple[Combination, ...] = ()
    notes: Tuple[str, ...] = ()
    # The part's place in the chain, for the overview of the Capabilities page
    role: str = ROLE_STEP
    step: str = ""  # the chain step the part performs (a step part), as the console names it
    takes: str = ""  # what it takes, in a few words
    gives: str = ""  # what it gives
    job_types: Tuple[str, ...] = ()  # the cluster job types that run it, so the console can say which nodes offer it
    schema_version: int = field(default=SCHEMA_VERSION)

    def validate(self) -> "ArchitectureDocument":
        """Fail on a dangling reference, so a typo in a spec cannot reach the page."""
        _require(self.role in (ROLE_STEP, ROLE_SUPPORT), f"{self.id}: unknown role {self.role}")
        lane_ids = [lane.id for lane in self.lanes]
        _require_unique("lane", lane_ids)
        meta_ids = [node.id for node in self.metamodel_nodes]
        node_ids = [node.id for node in self.nodes]
        _require_unique("metamodel node", meta_ids)
        _require_unique("node", node_ids)
        _require_unique("metamodel edge", [edge.id for edge in self.metamodel_edges])
        _require_unique("edge", [edge.id for edge in self.edges])
        for meta in self.metamodel_nodes:
            _require(meta.lane in lane_ids, f"{self.id}: metamodel node {meta.id} is in unknown lane {meta.lane}")
        for meta_edge in self.metamodel_edges:
            _require(meta_edge.source in meta_ids and meta_edge.target in meta_ids, f"{self.id}: metamodel edge {meta_edge.id} joins unknown nodes")
        for node in self.nodes:
            _require(node.lane in lane_ids, f"{self.id}: node {node.id} is in unknown lane {node.lane}")
            _require(node.implements is None or node.implements in meta_ids, f"{self.id}: node {node.id} implements unknown {node.implements}")
        meta_edge_ids = {edge.id for edge in self.metamodel_edges}
        for edge in self.edges:
            _require(edge.source in node_ids and edge.target in node_ids, f"{self.id}: edge {edge.id} joins unknown nodes")
            _require(edge.implements is None or edge.implements in meta_edge_ids, f"{self.id}: edge {edge.id} implements unknown {edge.implements}")
        for link in self.unsupported:
            _require(link.source in node_ids and link.target in node_ids, f"{self.id}: unsupported link {link.source} to {link.target} joins unknown nodes")
        for combination in self.combinations:
            _require(all(node_id in node_ids for node_id in combination.path), f"{self.id}: combination {combination.path} names an unknown node")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return to_plain(self)


def to_plain(value: Any) -> Any:
    """Dataclasses, tuples and enums as dicts, lists and plain values, for YAML and JSON. Infinity becomes UNBOUNDED."""
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: to_plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, float) and math.isinf(value):
        return UNBOUNDED if value > 0 else "-" + UNBOUNDED
    return value


def facts_of(*groups: Tuple[Fact, ...]) -> Tuple[Fact, ...]:
    merged: List[Fact] = []
    for group in groups:
        merged.extend(group)
    return tuple(merged)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_unique(kind: str, ids: List[str]) -> None:
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    _require(not duplicates, f"duplicate {kind} ids: {', '.join(duplicates)}")
