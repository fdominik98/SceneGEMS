"""The custom controller as a component of a vessel stack: one vessel's autopilot in its own container.

The runner gives it the vessel, the autopilot's gains (derived from the hull the simulator
generated) and, when the ASV system hands over a waypoint mission, that mission. Then, for
every control step, it turns the hull's observation and the heading and speed setpoint into the
actuator command of the hull's steering type (TwinThrustAutopilot): the port and starboard thrusts
of a skid steered hull, or the thrust and the helm angle of a hull with a rudder or vectored
thrust. With a mission, the controller's line-of-sight follower
(LosWaypointFollower) computes the setpoint of every scenario step from the vessel's state.

    -> {"op": "start", "seed": 7, "vessel": <ConcreteVessel.to_dict()>, "gains": {<AutopilotGains fields>},
        "mission": null or {"time_step": 1.0, "waypoints": [[x, y, speed, heading], ..]}}
    <- {"op": "started"}
    -> {"op": "guide", "index": 0, "time": 0.0, "target_time": 1.0, "own": [x, y, speed, heading]}   (with a mission only)
    <- {"op": "setpoint", "heading": .., "speed": ..}
    -> {"op": "step", "dt": 0.1, "hull": [heading, surge, yaw_rate, sway], "setpoint": [heading, speed]}
    <- {"op": "command", "thrusts": [port, starboard], "helm_angle": null, "force": .., "moment": .., "yaw_saturated": false, "surge_saturated": false}
       (a hull with a rudder or vectored thrust: "thrusts": [center], "helm_angle": <rad, positive turns to starboard>;
        force and moment are the surge force in N and the yaw moment in N m the command gives)

Entry point of the container:

    python -m scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server --port 12100
"""

from typing import Optional, Sequence

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_CONTROLLER, Message, Session, WireError, serve_component
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from scenegems_tool.vessel_stack.contracts.stack_services import controller_port
from scenegems_tool.vessel_stack.control_layers.custom.los_waypoint_follower import LosWaypointFollower
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, HullObservation, TwinThrustAutopilot

IMPLEMENTATION = "custom"


class CustomControllerSession(Session):
    def __init__(self) -> None:
        self._vessel: Optional[ConcreteVessel] = None
        self._autopilot: Optional[TwinThrustAutopilot] = None
        self._follower: Optional[LosWaypointFollower] = None

    def on_start(self, request: Message) -> Message:
        vessel = ConcreteActor.from_dict(request["vessel"])
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"actor {vessel.id} is not a vessel")
        self._vessel = vessel
        self._autopilot = TwinThrustAutopilot(AutopilotGains(**request["gains"]))
        self._follower = None
        mission = request.get("mission")
        if mission is not None:
            self._follower = LosWaypointFollower(vessel, [ActorState(*row) for row in mission["waypoints"]], float(mission["time_step"]))
            self._follower.start(int(request["seed"]))
        return {"op": "started"}

    def on_guide(self, request: Message) -> Message:
        if self._follower is None or self._vessel is None:
            raise WireError("guide needs a start with a waypoint mission")
        step = StepRequest(index=int(request["index"]), time=float(request["time"]), target_time=float(request["target_time"]))
        observation = VesselStateObservation(sim_time=step.time, vessel=self._vessel, own_state=ActorState(*request["own"]), target_states={})
        setpoint = self._follower.on_step(step, observation)
        return {"op": "setpoint", "heading": float(setpoint.heading), "speed": float(setpoint.speed)}

    def on_step(self, request: Message) -> Message:
        if self._autopilot is None:
            raise WireError("step before start")
        heading, speed = request["setpoint"]
        command = self._autopilot.command(float(heading), float(speed), HullObservation(*(float(value) for value in request["hull"])), float(request["dt"]))
        return {
            "op": "command",
            "thrusts": list(command.thrusts),
            "helm_angle": command.helm_angle,
            "force": command.force,
            "moment": command.moment,
            "yaw_saturated": command.yaw_saturated,
            "surge_saturated": command.surge_saturated,
        }


def main(argv: Optional[Sequence[str]] = None) -> None:
    serve_component(ROLE_CONTROLLER, IMPLEMENTATION, CustomControllerSession, argv, default_port=controller_port(0))


if __name__ == "__main__":
    main()
