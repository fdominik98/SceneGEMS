from typing import Callable, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.per_job.simulation_session_stack import claim_stack_ownership, schedule_force_destroy_session_stack, schedule_leftover_sweep
from scenegems_tool.gateway.protocol import ServerMessage, SimulationStatus, make_error_message
from scenegems_tool.subsystems.simulation.simulation_session import SimulationSession


class EmptySimulationSession(SimulationSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None], session_scope: Optional[InstanceScope] = None):
        """session_scope: the live session whose simulation this replaces; its stack is torn down. Without one
        (a new socket session) only stacks an earlier process left behind are removed, once per process."""
        super().__init__(send_payload, SimulationStatus.NOT_INITIALIZED)
        if session_scope is None:
            schedule_leftover_sweep()
        else:
            schedule_force_destroy_session_stack(session_scope, owner_generation=claim_stack_ownership(session_scope))

    def _destroy(self) -> None:
        pass

    def _status_update(self) -> SimulationStatus:
        return SimulationStatus.NOT_INITIALIZED

    def _send_scenario_chunks(self) -> None:
        pass

    def start_simulation_runtime(self) -> None:
        self.send_payload(make_error_message(message="Simulation is not initialized"))
