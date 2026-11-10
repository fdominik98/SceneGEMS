"""Runner side of a custom controller container: TwinThrustAutopilot's interface over the wire.

The Gazebo lockstep runner (gz_lockstep_runner.run_gz_lockstep) calls a CustomControllerLink
exactly as it calls a TwinThrustAutopilot in its own process. MissionGuidance is the lockstep
participant of a vessel whose ASV software hands the controller a waypoint mission: it starts the
software, passes its mission on, and from then on the controller steers by itself.
"""

import dataclasses
from typing import Any, Dict, Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_software.asv_software_link import AsvSoftwareLink
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_CONTROLLER, Endpoint, LineClient, WireError, state_row
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, HullObservation, ThrustCommand


class CustomControllerLink:
    def __init__(self, endpoint: Endpoint, vessel: ConcreteVessel, gains: AutopilotGains):
        self.gains = gains
        self._vessel = vessel
        self._mission: Optional[Dict[str, Any]] = None
        self._seed = 0
        self._client = LineClient(endpoint, ROLE_CONTROLLER)

    def connect(self, timeout_s: float = 300.0) -> "CustomControllerLink":
        self._client.connect(timeout_s)
        return self

    def load_mission(self, mission: Dict[str, Any], seed: int) -> None:
        """The waypoint mission the controller follows from its next reset on."""
        self._mission = mission
        self._seed = int(seed)

    def reset(self) -> None:
        """Start the controller for a run: fresh integrators, and the mission when one is loaded."""
        self._client.request({"op": "start", "seed": self._seed, "vessel": self._vessel.to_dict(), "gains": dataclasses.asdict(self.gains), "mission": self._mission})

    def guide(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        """The setpoint of a scenario step from the controller's own waypoint follower."""
        reply = self._client.request({"op": "guide", "index": request.index, "time": request.time, "target_time": request.target_time, "own": state_row(observation.own_state)})
        return HeadingSpeedCommand(heading=float(reply["heading"]), speed=float(reply["speed"]))

    def command(self, desired_heading: float, desired_speed: float, observation: HullObservation, dt: float) -> ThrustCommand:
        reply = self._client.request(
            {
                "op": "step",
                "dt": float(dt),
                "hull": [float(observation.heading), float(observation.surge), float(observation.yaw_rate)],
                "setpoint": [float(desired_heading), float(desired_speed)],
            }
        )
        return ThrustCommand(port=float(reply["port"]), starboard=float(reply["starboard"]), yaw_saturated=bool(reply["yaw_saturated"]), surge_saturated=bool(reply["surge_saturated"]))

    def close(self) -> None:
        self._client.close()


class MissionGuidance:
    """Lockstep participant of a vessel whose ASV software gives its controller a waypoint mission."""

    def __init__(self, asv_software: AsvSoftwareLink, controller: CustomControllerLink):
        self.participant_id = asv_software.participant_id
        self._asv_software = asv_software
        self._controller = controller

    def start(self, seed: int) -> None:
        self._asv_software.start(seed)
        if self._asv_software.mission is None:
            raise WireError(f"{self.participant_id} handed over no waypoint mission")
        self._controller.load_mission(self._asv_software.mission, seed)

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        return self._controller.guide(request, observation)

    def report(self) -> Dict[str, Any]:
        return self._asv_software.report()
