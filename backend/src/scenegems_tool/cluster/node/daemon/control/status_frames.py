"""Hello and Heartbeat: what the node tells its master about itself.

Hello opens every connection: identity, the machine, slots per job type, components, labels, resources, the
fingerprints of the local images and the leases still running from before a reconnect.
Heartbeats repeat the changing part at the interval the master's Welcome sets.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Protocol

from scenegems_tool.cluster.fingerprints.components import ordered
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello
from scenegems_tool.cluster.protocol.node_description import NodeResources, SlotOffer, SlotUsage

_logger = logging.getLogger(__name__)

UNKNOWN_REVISION = "unknown"


class LeaseState(Protocol):
    def running_lease_ids(self) -> List[str]: ...

    def slots_in_use(self) -> SlotUsage: ...


@dataclass
class StatusFrames:
    node_id: str
    node_name: str
    software_revision: str
    slots: Dict[JobType, int]
    components: FrozenSet[str]
    labels: Dict[str, str]
    resources: Callable[[], NodeResources]
    fingerprints: Callable[[], Dict[str, str]]
    leases: LeaseState
    machine: Optional[str] = None

    def hello(self) -> Hello:
        return Hello(
            node_id=self.node_id,
            node_name=self.node_name,
            software_revision=self.software_revision,
            machine=self.machine,
            slots=[SlotOffer(job_type=job_type, slots=slots) for job_type, slots in sorted(self.slots.items(), key=lambda item: item[0].value)],
            components=list(ordered(self.components)),
            labels=dict(self.labels),
            resources=self.resources(),
            fingerprints=self._fingerprints(),
            running_lease_ids=self.leases.running_lease_ids(),
        )

    def heartbeat(self) -> Heartbeat:
        return Heartbeat(resources=self.resources(), slots_in_use=self.leases.slots_in_use(), running_lease_ids=self.leases.running_lease_ids())

    def _fingerprints(self) -> Dict[str, str]:
        try:
            return dict(self.fingerprints())
        except Exception as error:  # Docker unreachable: the master sees no images and leases nothing that needs one
            _logger.warning("Cannot read the image fingerprints: %s: %s", type(error).__name__, error)
            return {}


def software_revision(configured: Optional[str]) -> str:
    """The configured revision (the release's, written into the node's .env by the deployment tool), else "unknown"."""
    return configured or UNKNOWN_REVISION
