"""What the subsystem specs share: the measured facts file and the check that a spec exists for every implementation.

Each subsystem declares its metamodel and its implementations in a `*_specs.py` next to its code (the pattern of
vessel_stack/**/**_specs.py) and builds an ArchitectureDocument from them. Declared values live in the spec. Measured
values live only in measured_capabilities.yaml in this folder, keyed by the id of the node or edge they describe:

    monitoring/live:
      facts:
        - {key: throughput, label: Throughput, value: 340, unit: scenes/s, note: "..."}
      evidence: how and when it was measured

The vessel stack keeps its own measured file (vessel_stack/registry/measured_capabilities.yaml).
"""

import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Type

import yaml

from scenegems_tool.architecture.architecture_model import GROUP_CAPABILITY, GROUP_PROPERTY, STATUS_AVAILABLE, ArchitectureEdge, ArchitectureNode, Fact, facts_of

SUBSYSTEM_MEASUREMENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "measured_capabilities.yaml")
_FACT_FIELDS = {"key", "label", "value", "unit", "note"}


@dataclass(frozen=True)
class MeasuredFacts:
    facts: Tuple[Fact, ...] = ()
    evidence: str = ""


def parse_measured_facts(spec_id: str, entry: Mapping[str, Any]) -> MeasuredFacts:
    unknown = set(entry) - {"facts", "evidence"}
    if unknown:
        raise ValueError(f"{spec_id}: unknown measured fields {sorted(unknown)}")
    facts = []
    for item in entry.get("facts") or []:
        extra = set(item) - _FACT_FIELDS
        if extra or "key" not in item or "label" not in item or "value" not in item:
            raise ValueError(f"{spec_id}: a measured fact needs key, label and value and takes only {sorted(_FACT_FIELDS)}: {dict(item)}")
        facts.append(Fact(item["key"], item["label"], item["value"], GROUP_CAPABILITY, measured=True, unit=item.get("unit"), note=item.get("note")))
    return MeasuredFacts(tuple(facts), str(entry.get("evidence", "")).strip())


def load_measured_facts(path: str = SUBSYSTEM_MEASUREMENTS_FILE) -> Dict[str, MeasuredFacts]:
    with open(path, encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return {str(spec_id): parse_measured_facts(str(spec_id), entry or {}) for spec_id, entry in data.items()}


@lru_cache(maxsize=1)
def default_measured_facts() -> Mapping[str, MeasuredFacts]:
    return load_measured_facts()


def measured_for(spec_id: str, measurements: Optional[Mapping[str, MeasuredFacts]] = None) -> MeasuredFacts:
    return (default_measured_facts() if measurements is None else measurements).get(spec_id, MeasuredFacts())


POOL_SIZE = "at most as many tasks run at once as the worker node has slots for this kind of work; the others wait in arrival order"
TASK_STATES = "received, queued, running, then finished, failed or aborted"


def pool_facts(request: str, tasks: str, seed: str, publishes: str) -> Tuple[Fact, ...]:
    """What a subsystem's request entry says about its pool: the request's name, the tasks it becomes, the pool, the seed and what is published."""
    return (
        Fact("request", "Request", request, GROUP_PROPERTY),
        Fact("tasks", "Tasks", tasks, GROUP_CAPABILITY),
        Fact("pool", "Pool", POOL_SIZE, GROUP_CAPABILITY),
        Fact("seed", "Seed", seed, GROUP_CAPABILITY),
        Fact("task_states", "Task states", TASK_STATES, GROUP_PROPERTY),
        Fact("publishes", "Publishes", publishes, GROUP_PROPERTY),
    )


def spec_node(
    document_id: str,
    local: str,
    lane: str,
    label: str,
    description: str,
    implements: Optional[str],
    *,
    facts: Tuple[Fact, ...] = (),
    tags: Tuple[str, ...] = (),
    status: str = STATUS_AVAILABLE,
    measurements: Optional[Mapping[str, MeasuredFacts]] = None,
) -> ArchitectureNode:
    """A node "<document>/<local>" with its declared facts followed by the measured ones filed under the same id."""
    node_id = f"{document_id}/{local}"
    measured = measured_for(node_id, measurements)
    return ArchitectureNode(node_id, lane, label, description, implements, status, facts_of(facts, measured.facts), tags=tags, evidence=measured.evidence)


def spec_edge(
    document_id: str,
    source: str,
    target: str,
    label: str,
    implements: Optional[str],
    *,
    description: str = "",
    kind: str = "adapter",
    facts: Tuple[Fact, ...] = (),
    measurements: Optional[Mapping[str, MeasuredFacts]] = None,
) -> ArchitectureEdge:
    """An edge between two local node ids; its id is "<document>/<source>__<target>"."""
    edge_id = f"{document_id}/{source}__{target}"
    measured = measured_for(edge_id, measurements)
    return ArchitectureEdge(
        edge_id,
        f"{document_id}/{source}",
        f"{document_id}/{target}",
        label,
        description,
        implements,
        kind,
        facts=facts_of(facts, measured.facts),
        evidence=measured.evidence,
    )


def check_measured_ids(measurements: Mapping[str, MeasuredFacts], known_ids: Iterable[str]) -> None:
    """Fail on measured entries that match no node or edge, since a typo would drop a measurement."""
    unknown = sorted(set(measurements) - set(known_ids))
    if unknown:
        raise ValueError(f"Measured facts for unknown specs: {', '.join(unknown)}")


def check_covers_enum(enum_type: Type[Enum], declared_ids: Iterable[str], what: str) -> None:
    """Fail when an implementation id of the enum has no spec, or a spec names no implementation: adding a generator or monitor forces its spec."""
    declared = set(declared_ids)
    implemented = {member.value for member in enum_type}
    missing = sorted(implemented - declared)
    if missing:
        raise ValueError(f"{what}: no architecture spec for {', '.join(missing)}; declare it in the subsystem's specs module")
    extra = sorted(declared - implemented)
    if extra:
        raise ValueError(f"{what}: architecture spec for {', '.join(extra)}, which {enum_type.__name__} does not define")
