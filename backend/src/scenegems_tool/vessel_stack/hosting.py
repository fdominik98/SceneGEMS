"""Where the layers of a vessel stack run: in the caller's process, or each in its own container.

The lockstep runners (kinematic_runner, gz_lockstep_runner, mavlink_lockstep_runner) ask a
hosting for every layer they step, and step what they get the same way:

- InProcessHosting builds the layers in the caller's process. Tests and the calibration
  measurements use it; it needs no Docker.
- ContainerHosting connects to the stack's containers, one per layer: an ASV software and a
  controller container per vessel and one simulator per scenario. Cluster jobs and live sessions
  use it; simulation_docker_stack.py generates the services it connects to.

Both give the same run for the same inputs: the containers run the classes the in-process
hosting builds, and the wire protocol carries every float bit for bit.

A hosting is used for one run and closed after it.
"""

from typing import Any, Iterable, List, Mapping, Optional, Protocol, Tuple

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.asv_software.asv_software_runtime import ParticipantRequest, asv_software_runtime
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.stack_services import (
    KINEMATIC_SIM_SERVICE,
    asv_software_endpoint,
    asv_software_service_name,
    controller_endpoint,
    controller_service_name,
    kinematic_sim_endpoint,
)

DEFAULT_CONNECT_TIMEOUT_S = 300.0


class StackHosting(Protocol):
    def asv_software(self, request: ParticipantRequest) -> LockstepParticipant:
        """The lockstep participant of one vessel's ASV software."""

    def kinematic_simulation(self, initial_scene: ConcreteScene, dt: float, participant_ids: Iterable[str]) -> Any:
        """The kinematic simulator of a scenario, with KinematicSimulation's interface."""

    def custom_control(self, request: ParticipantRequest, gains: Any) -> Tuple[LockstepParticipant, Any]:
        """One vessel on the custom controller: the participant that sets its heading and speed, and its autopilot (TwinThrustAutopilot's interface)."""

    def close(self) -> None:
        """Release what the hosting opened for the run."""


class InProcessHosting:
    def asv_software(self, request: ParticipantRequest) -> LockstepParticipant:
        return asv_software_runtime(request.asv_software).in_process(request)

    def kinematic_simulation(self, initial_scene: ConcreteScene, dt: float, participant_ids: Iterable[str]) -> Any:
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

        return KinematicSimulation(initial_scene, dt, participant_ids)

    def custom_control(self, request: ParticipantRequest, gains: Any) -> Tuple[LockstepParticipant, Any]:
        from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import TwinThrustAutopilot

        return self.asv_software(request), TwinThrustAutopilot(gains)

    def close(self) -> None:
        pass


class ContainerHosting:
    """Links to the containers of one stack.

    endpoints replaces the address of a service, by service name: by default every component is
    reached by its service name on the stack's network (contracts/stack_services.py), which is
    where a job's runner and a live session's scenario execution service are.
    """

    def __init__(self, endpoints: Optional[Mapping[str, Endpoint]] = None, *, connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S):
        self._endpoints = dict(endpoints or {})
        self._connect_timeout_s = connect_timeout_s
        self._links: List[Any] = []

    def asv_software(self, request: ParticipantRequest) -> LockstepParticipant:
        from scenegems_tool.vessel_stack.asv_software.asv_software_link import AsvSoftwareLink

        endpoint = self._endpoint(asv_software_service_name(request.agent_name), asv_software_endpoint(request.agent_name))
        return self._connected(AsvSoftwareLink(endpoint, request))

    def kinematic_simulation(self, initial_scene: ConcreteScene, dt: float, participant_ids: Iterable[str]) -> Any:
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_link import KinematicSimLink

        return self._connected(KinematicSimLink(self._endpoint(KINEMATIC_SIM_SERVICE, kinematic_sim_endpoint()), initial_scene, dt, participant_ids))

    def custom_control(self, request: ParticipantRequest, gains: Any) -> Tuple[LockstepParticipant, Any]:
        from scenegems_tool.vessel_stack.control_layers.custom.custom_controller_link import CustomControllerLink, MissionGuidance

        endpoint = self._endpoint(controller_service_name(request.agent_name), controller_endpoint(request.agent_name))
        controller = self._connected(CustomControllerLink(endpoint, request.vessel, gains))
        asv_software = self.asv_software(request)
        return (MissionGuidance(asv_software, controller) if request.hands_over_mission else asv_software), controller

    def close(self) -> None:
        for link in self._links:
            link.close()
        self._links = []

    def _endpoint(self, service: str, default: Endpoint) -> Endpoint:
        return self._endpoints.get(service, default)

    def _connected(self, link: Any) -> Any:
        self._links.append(link)  # before connecting, so a failed connect is closed with the rest
        return link.connect(self._connect_timeout_s)


def in_stack_hosting() -> StackHosting:
    """The hosting of code that runs inside a stack, next to its containers: a job's runner, a live session's driver."""
    return ContainerHosting()


def participant_reports(participants: Mapping[int, LockstepParticipant]) -> Mapping[int, Mapping[str, Any]]:
    """What each ASV software reports for the run record, by vessel id; software without a report is left out. Call it before the hosting is closed."""
    reports = {}
    for vessel_id, participant in sorted(participants.items()):
        report = getattr(participant, "report", None)
        if report is not None:
            content = report()
            if content:
                reports[vessel_id] = content
    return reports
