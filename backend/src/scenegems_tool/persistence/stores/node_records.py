"""Detached snapshots of a node as the stores return them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.node_description import NodeResources
from scenegems_tool.persistence.schema import NodeRow, NodeStatus


@dataclass(frozen=True)
class SlotState:
    slots: int
    slots_in_use: int  # as the node last reported it


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    name: str
    status: NodeStatus
    labels: Dict[str, str]
    software_revision: str
    resources: NodeResources
    slots: Dict[JobType, SlotState]
    fingerprints: Dict[str, str]  # image name to build fingerprint
    registered_at: datetime
    last_seen_at: datetime
    machine: Optional[str] = None  # the machine the node runs on, as it reported in its Hello
    components: Tuple[str, ...] = ()  # the components it offers, sorted

    @classmethod
    def from_row(cls, row: NodeRow) -> "NodeRecord":
        return cls(
            node_id=row.id,
            name=row.name,
            status=row.status,
            labels=dict(row.labels),
            software_revision=row.software_revision,
            resources=NodeResources(cpus=row.cpus, memory_mb=row.memory_mb, free_memory_mb=row.free_memory_mb, free_disk_mb=row.free_disk_mb, load_average=row.load_average),
            slots={capability.job_type: SlotState(slots=capability.slots, slots_in_use=capability.slots_in_use) for capability in row.capabilities},
            fingerprints={fingerprint.image: fingerprint.fingerprint for fingerprint in row.fingerprints},
            registered_at=row.registered_at,
            last_seen_at=row.last_seen_at,
            machine=row.machine,
            components=tuple(component.component for component in row.components),
        )
