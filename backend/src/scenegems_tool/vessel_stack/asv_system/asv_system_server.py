"""Serves a LockstepParticipant as an ASV system component over the lockstep wire protocol.

For ASV system that is part of the SceneGEMS backend (replay). Software that lives in an image
of its own serves the protocol itself (usv_navigation/usv_navigation_server.py).
"""

from typing import Any, Dict, Optional, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant, StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Message, Session, WireError
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation


class ParticipantSession(Session):
    """A subclass builds its participant from the start message; this class steps it."""

    def __init__(self) -> None:
        self._vessel: Optional[ConcreteVessel] = None
        self._participant: Optional[LockstepParticipant] = None

    def build(self, vessel: Message, config: Message) -> Tuple[ConcreteVessel, LockstepParticipant]:
        """The vessel model and the participant of one run."""
        raise NotImplementedError

    def mission(self, config: Message) -> Optional[Dict[str, Any]]:
        """The waypoint mission the software hands to its controller; None for software that commands every step."""
        del config
        return None

    def on_start(self, request: Message) -> Message:
        self._vessel, self._participant = self.build(request["vessel"], request["config"])
        self._participant.start(int(request["seed"]))
        reply: Message = {"op": "started", "participant_id": self._participant.participant_id}
        mission = self.mission(request["config"])
        if mission is not None:
            reply["mission"] = mission
        return reply

    def on_step(self, request: Message) -> Message:
        if self._participant is None or self._vessel is None:
            raise WireError("step before start")
        observation = VesselStateObservation(
            sim_time=float(request["time"]),
            vessel=self._vessel,
            own_state=ActorState(*request["own"]),
            target_states={int(actor_id): ActorState(*row) for actor_id, row in request["targets"].items()},
        )
        step = StepRequest(index=int(request["index"]), time=float(request["time"]), target_time=float(request["target_time"]))
        command = self._participant.on_step(step, observation)
        return {"op": "command", "heading": float(command.heading), "speed": float(command.speed)}

    def on_report(self, request: Message) -> Message:
        del request
        report = getattr(self._participant, "report", None)
        return {"op": "report", "report": report() if report is not None else {}}
