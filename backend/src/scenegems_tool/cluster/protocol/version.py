"""Version of the master-node protocol.

Master and node must speak the same version. Every frame carries it, and a frame of
another version is rejected before its body is read, so a version change can reshape
any message without producing confusing validation errors on the other side.

Version 2 (Phase 4): payloads and results may hold artifact references (artifacts.py), the
generation payloads take a seed, trajectory results say whether the plan is complete, the
kinematic simulation takes a live monitor, and calibration.deviation is a job type.

Version 3 (Phase 5): Hello may name the node's machine, and running simulations are observed
live (Observe from the master, ObservationFrames from the node).

Version 4: no pairing, credentials or TLS. A node names itself in its Hello (its node id is its
node name) and in the node id header of the artifact routes; master and nodes trust the VPN.

Version 5: simulation.ardupilot is split into simulation.ardupilot_sim and simulation.gazebo, so a
node offers SITL's own physics and Gazebo as separate capabilities.
"""

PROTOCOL_VERSION = 5


class ProtocolVersionMismatch(ValueError):
    """Raised when the other side speaks a different protocol version."""

    def __init__(self, received: object, expected: int = PROTOCOL_VERSION) -> None:
        self.received = received
        self.expected = expected
        super().__init__(f"Incompatible cluster protocol version: received {received!r}, this side speaks {expected}. Update the master and every node to the same SceneGEMS revision.")


def ensure_compatible(received: object) -> None:
    if received != PROTOCOL_VERSION:
        raise ProtocolVersionMismatch(received)
