"""The kinematic simulator as a component of a vessel stack: the simulated world of one scenario.

One container per scenario, as the Gazebo container is, and with the same shape of conversation:
the runner starts the world, then sends every vessel's command for a step and gets every actor's
state after it. It is the fast, simplified alternative to Gazebo: ConcreteVessel.simulate instead
of physics, heading and speed commands instead of thrust.

    -> {"op": "start", "scene": <ConcreteScene.to_dict()>, "dt": 1.0}
    <- {"op": "state", "index": 0, "actors": [0, 1], "states": [[x, y, speed, heading], ..]}   (states in the order of actors)
    -> {"op": "step", "commands": {"<vessel id>": [heading, speed]}}                            (an uncommanded vessel holds heading and speed)
    <- {"op": "state", "index": 1, "states": [..]}

The clock's acknowledgements stay with the runner (kinematic_sim_link.py), which is the one that
knows the participants. Entry point of the container:

    python -m scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server --port 11430
"""

from typing import Optional, Sequence

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_SIMULATOR, Message, Session, WireError, serve_component, state_row
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand
from scenegems_tool.vessel_stack.contracts.stack_services import KINEMATIC_SIM_PORT
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

IMPLEMENTATION = "kinematic"


class KinematicSimSession(Session):
    def __init__(self) -> None:
        self._simulation: Optional[KinematicSimulation] = None
        self._index = 0

    def on_start(self, request: Message) -> Message:
        self._simulation = KinematicSimulation(ConcreteScene.from_dict(request["scene"]), float(request["dt"]), participant_ids=())
        self._index = 0
        return {**self._state(), "actors": [actor.id for actor in self._simulation.actors]}

    def on_step(self, request: Message) -> Message:
        if self._simulation is None:
            raise WireError("step before start")
        commands = {int(vessel_id): HeadingSpeedCommand(heading=float(heading), speed=float(speed)) for vessel_id, (heading, speed) in request["commands"].items()}
        self._simulation.step(commands, acks=())
        self._index += 1
        return self._state()

    def _state(self) -> Message:
        return {"op": "state", "index": self._index, "states": [state_row(state) for state in self._simulation.snapshot()]}


def main(argv: Optional[Sequence[str]] = None) -> None:
    serve_component(ROLE_SIMULATOR, IMPLEMENTATION, KinematicSimSession, argv, default_port=KINEMATIC_SIM_PORT)


if __name__ == "__main__":
    main()
