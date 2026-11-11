"""Version of the control node to worker node protocol.

Control node and worker node must speak the same version. Every frame carries it, and a frame of
another version is rejected before its body is read, so a version change can reshape
any message without producing confusing validation errors on the other side.

Version 2 (Phase 4): payloads and results may hold artifact references (artifacts.py), the
generation payloads take a seed, trajectory results say whether the plan is complete, the
kinematic simulation takes a live monitor, and calibration.deviation is a job type.

Version 3 (Phase 5): Hello may name the worker node's machine, and running simulations are observed
live (Observe from the control node, ObservationFrames from the worker node).

Version 4: no pairing, credentials or TLS. A worker node names itself in its Hello (its worker node id is its
worker node name) and in the worker node id header of the artifact routes; control node and worker nodes trust the VPN.

Version 5: simulation.ardupilot is split into simulation.ardupilot_sim and simulation.gazebo, so a
worker node offers SITL's own physics and Gazebo as separate capabilities.

Version 6: a worker node's capability is a set of components (vessel stack layers and subsystems). Hello
carries slots per job type and components; job requirements carry the components a job needs. The
three simulation job types are one, simulation, whose payload names its runner (kinematic, ardupilot).

Version 7: design_space_exploration is a job type (the Refinery model generator in a container per job), and a
result field that holds a list (ArtifactField.many) is stored as one artifact per item.
Version 8: the master is the control node and a node is a worker node. The fields follow: control_node_id
(Hello, Welcome), worker_node_id, allowed_worker_nodes; the control socket is /cluster/worker-node/control and
the artifact routes read the X-Worker-Node-Id header.

Version 9: the ASV software of a vessel stack is its ASV system. A vessel's stack names it asv_system, and the
components are asv_system/replay and asv_system/usv_navigation.

Version 10: Welcome carries the worker node's instance number. The pooled services of a worker node are named
after it on the cluster broker (scene-generation-subsystem-<number>), whose topics no longer have a level for
the control node, the worker node or the instance.

Version 11: attended simulations. The simulation job has a runner that brings its stack up and waits for the
operator: StartJob from the control node starts its run, and JobStatus may carry a detail (the phase of the run,
the ports the stack published for a ground control station).
"""

PROTOCOL_VERSION = 11


class ProtocolVersionMismatch(ValueError):
    """Raised when the other side speaks a different protocol version."""

    def __init__(self, received: object, expected: int = PROTOCOL_VERSION) -> None:
        self.received = received
        self.expected = expected
        super().__init__(f"Incompatible cluster protocol version: received {received!r}, this side speaks {expected}. Update the control node and every worker node to the same SceneGEMS revision.")


def ensure_compatible(received: object) -> None:
    if received != PROTOCOL_VERSION:
        raise ProtocolVersionMismatch(received)
