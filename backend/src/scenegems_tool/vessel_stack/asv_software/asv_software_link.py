"""Runner side of an ASV software container: a LockstepParticipant over the lockstep wire protocol.

A lockstep runner steps an AsvSoftwareLink exactly as it steps a participant in its own process.
The link works for every ASV software: what differs between them is the start config
(asv_software_runtime.AsvSoftwareRuntime.start_config) and the image behind the endpoint.
"""

from typing import Any, Dict, Optional

from scenegems_tool.vessel_stack.asv_software.asv_software_runtime import ParticipantRequest, asv_software_runtime, vessel_limits
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SOFTWARE, Endpoint, LineClient, WireError, state_row, state_rows
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation


class AsvSoftwareLink:
    def __init__(self, endpoint: Endpoint, request: ParticipantRequest):
        self.participant_id = request.participant_id
        self.mission: Optional[Dict[str, Any]] = None  # set by start for software that hands over a waypoint mission
        self._vessel = vessel_limits(request.vessel)
        self._config = asv_software_runtime(request.asv_software).start_config(request)
        self._client = LineClient(endpoint, ROLE_ASV_SOFTWARE)

    def connect(self, timeout_s: float = 300.0) -> "AsvSoftwareLink":
        self._client.connect(timeout_s)
        return self

    def start(self, seed: int) -> None:
        reply = self._client.request({"op": "start", "seed": int(seed), "vessel": self._vessel, "config": self._config})
        if reply.get("participant_id") != self.participant_id:
            raise WireError(f"{self._client.endpoint} runs {reply.get('participant_id')}, the stack expects {self.participant_id}")
        self.mission = reply.get("mission")

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        reply = self._client.request(
            {
                "op": "step",
                "index": request.index,
                "time": request.time,
                "target_time": request.target_time,
                "own": state_row(observation.own_state),
                "targets": state_rows(observation.target_states),
            }
        )
        return HeadingSpeedCommand(heading=float(reply["heading"]), speed=float(reply["speed"]))

    def report(self) -> Dict[str, Any]:
        """What the software wants in the run record (USV Navigation: its transitions and when it reached the goal)."""
        return dict(self._client.request({"op": "report"}).get("report") or {})

    def close(self) -> None:
        self._client.close()
