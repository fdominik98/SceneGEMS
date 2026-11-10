"""One connected worker node: its control socket, its latest facts and the leases it holds.

The session's lease map is how the control node checks that a frame about a lease comes from the
worker node the lease belongs to; lease ids are random, but a worker node must never act on another
worker node's job. It holds every lease offered to this worker node on this connection and every active
lease the worker node kept across a reconnect.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, List, Optional, Protocol, Set

from scenegems_tool.cluster.fingerprints.comparison import FingerprintMismatch
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.persistence.stores import Lease, WorkerNodeRecord


class ControlSocket(Protocol):
    """The worker node's end of the control link as the control node uses it; see control_link/."""

    @property
    def usable_components(self) -> FrozenSet[str]:
        """The worker node's components whose images match the release."""
        return frozenset(self.record.components) - self.stale_components

    async def send(self, frame: ProtocolFrame) -> bool: ...  # False when the frame could not be sent

    async def close(self, code: int, reason: str) -> None: ...


@dataclass(eq=False)
class WorkerNodeSession:
    worker_node_id: str
    socket: ControlSocket
    record: WorkerNodeRecord  # as the store returned it after the Hello or the latest heartbeat
    connected_at: datetime
    leases: Dict[str, str] = field(default_factory=dict)  # lease id to job id
    pending_offers: Set[str] = field(default_factory=set)  # offered on this connection, not accepted yet
    out_of_date: List[FingerprintMismatch] = field(default_factory=list)  # the images of its components that differ from the release
    stale_components: FrozenSet[str] = frozenset()  # the components that need one of those images: unusable until the worker node is updated
    ready: bool = False  # Welcome sent and leases reconciled: the scheduler may offer
    replaced: bool = False  # a newer connection of the same worker node took over
    closed: bool = False

    @property
    def usable_components(self) -> FrozenSet[str]:
        """The worker node's components whose images match the release."""
        return frozenset(self.record.components) - self.stale_components

    async def send(self, frame: ProtocolFrame) -> bool:
        if self.closed:
            return False
        return await self.socket.send(frame)

    async def close(self, code: int, reason: str) -> None:
        if not self.closed:
            self.closed = True
            await self.socket.close(code, reason)

    def offered(self, lease: Lease) -> None:
        self.leases[lease.lease_id] = lease.job.job_id
        self.pending_offers.add(lease.lease_id)

    def holds(self, lease: Lease) -> None:
        self.leases[lease.lease_id] = lease.job.job_id
        self.pending_offers.discard(lease.lease_id)

    def owns(self, lease_id: str, job_id: Optional[str] = None) -> bool:
        return lease_id in self.leases and (job_id is None or self.leases[lease_id] == job_id)

    def job_of(self, lease_id: str) -> str:
        return self.leases.get(lease_id, "")

    def forget(self, lease_id: str) -> None:
        self.leases.pop(lease_id, None)
        self.pending_offers.discard(lease_id)

    def hand_over(self) -> None:
        """A newer connection takes over the worker node: it reconciles every lease from the store, so this one forgets them."""
        self.replaced = True
        self.leases.clear()
        self.pending_offers.clear()
