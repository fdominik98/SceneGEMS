"""The replay ASV software as a component of a vessel stack, and how a run configures it.

Replay follows the generated trajectory of its vessel. Towards a control layer that takes heading
and speed commands it commands every step (ReplayFollower). Towards the custom controller it hands
the trajectory over as a waypoint mission, which the controller's line-of-sight follower steers
(control_layers/custom/los_waypoint_follower.py), and commands nothing itself.

    "config": {"vessel": <ConcreteVessel.to_dict()>, "time_step": 1.0, "reference": [[x, y, speed, heading], ..], "output": "heading_speed_cmd" | "waypoint_mission"}

Entry point of the container:

    python -m scenegems_tool.vessel_stack.asv_software.replay.replay_server --port 11410
"""

from typing import Any, Dict, Optional, Sequence, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from scenegems_tool.vessel_stack.asv_software.asv_software_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_software.asv_software_server import ParticipantSession
from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SOFTWARE, Message, serve_component, state_row
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.stack_services import ASV_SOFTWARE_PORT

IMPLEMENTATION = "replay"


def replay_in_process(request: ParticipantRequest) -> LockstepParticipant:
    """Replay in the caller's process: the follower that commands every step, or the controller's waypoint follower for a mission."""
    if request.hands_over_mission:
        from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower

        return LosWaypointFollower(request.vessel, request.reference_states, request.trajectories.time_step)
    return ReplayFollower(request.vessel, request.reference_states, request.trajectories.time_step)


def replay_start_config(request: ParticipantRequest) -> Dict[str, Any]:
    return {
        "vessel": request.vessel.to_dict(),
        "time_step": float(request.trajectories.time_step),
        "reference": [state_row(state) for state in request.reference_states],
        "output": (Port.WAYPOINT_MISSION if request.hands_over_mission else Port.HEADING_SPEED_CMD).value,
    }


class ReplaySession(ParticipantSession):
    def build(self, vessel: Message, config: Message) -> Tuple[ConcreteVessel, LockstepParticipant]:
        del vessel  # the follower needs the whole vessel model, which the config carries
        model = ConcreteActor.from_dict(config["vessel"])
        if not isinstance(model, ConcreteVessel):
            raise ValueError(f"actor {model.id} is not a vessel")
        return model, ReplayFollower(model, [ActorState(*row) for row in config["reference"]], float(config["time_step"]))

    def mission(self, config: Message) -> Optional[Dict[str, Any]]:
        if config["output"] != Port.WAYPOINT_MISSION.value:
            return None
        return {"time_step": float(config["time_step"]), "waypoints": config["reference"]}


def main(argv: Optional[Sequence[str]] = None) -> None:
    serve_component(ROLE_ASV_SOFTWARE, IMPLEMENTATION, ReplaySession, argv, default_port=ASV_SOFTWARE_PORT)


if __name__ == "__main__":
    main()
