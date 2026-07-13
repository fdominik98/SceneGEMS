from typing import Callable

from scenegems_tool.backend_service.protocol import ServerMessage, SimulationStatus, make_error_message
from scenegems_tool.simulators.scenegems-scenario-execution-subsystem_container import (
    claim_stack_ownership,
    schedule_force_destroy_scenario_execution_stack,
)
from scenegems_tool.simulators.simulation_session import SimulationSession


class EmptySimulationSession(SimulationSession):
    def __init__(self, send_payload: Callable[[ServerMessage], None]):
        super().__init__(send_payload, SimulationStatus.NOT_INITIALIZED)
        stack_generation = claim_stack_ownership()
        schedule_force_destroy_scenario_execution_stack(owner_generation=stack_generation)

    def _destroy(self) -> None:
        pass

    def _status_update(self) -> SimulationStatus:
        return SimulationStatus.NOT_INITIALIZED

    def _send_scenario_chunks(self) -> None:
        pass

    def start_simulation_runtime(self) -> None:
        self.send_payload(make_error_message(message="Simulation is not initialized"))
