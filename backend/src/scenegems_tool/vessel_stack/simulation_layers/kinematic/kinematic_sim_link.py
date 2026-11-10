"""Runner side of the kinematic simulator's container: KinematicSimulation's interface over the wire.

The lockstep runner (kinematic_runner.run_lockstep) steps a KinematicSimLink exactly as it steps
a KinematicSimulation in process. The link keeps the lockstep clock, since the runner knows the
participants, and the container integrates the vessels (kinematic_sim_server.py).
"""

from typing import Dict, Iterable, Mapping, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, StepAck, StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_SIMULATOR, Endpoint, LineClient, WireError
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_specs import KINEMATIC_LAYER


class KinematicSimLink:
    spec = KINEMATIC_LAYER

    def __init__(self, endpoint: Endpoint, initial_scene: ConcreteScene, dt: float, participant_ids: Iterable[str]):
        self.dt = dt
        self.clock = LockstepClock(dt, participant_ids)
        self.actors: Tuple[ConcreteActor, ...] = tuple(initial_scene.actors)
        self._initial_scene = initial_scene
        self._vessels: Dict[int, ConcreteVessel] = {actor.id: actor for actor in self.actors if isinstance(actor, ConcreteVessel)}
        self._states: Dict[int, ActorState] = {}
        self._client = LineClient(endpoint, ROLE_SIMULATOR)

    def connect(self, timeout_s: float = 300.0) -> "KinematicSimLink":
        """Connect and start the world from the initial scene."""
        self._client.connect(timeout_s)
        reply = self._client.request({"op": "start", "scene": self._initial_scene.to_dict(), "dt": self.dt})
        actor_ids = [actor.id for actor in self.actors]
        if reply.get("actors") != actor_ids:
            raise WireError(f"the simulator at {self._client.endpoint} holds actors {reply.get('actors')}, the runner {actor_ids}")
        self._take_states(reply)
        return self

    @property
    def time(self) -> float:
        return self.clock.time

    def step_request(self) -> StepRequest:
        return self.clock.request()

    def observe(self, vessel_id: int) -> VesselStateObservation:
        return VesselStateObservation(
            sim_time=self.clock.time,
            vessel=self._vessels[vessel_id],
            own_state=self._states[vessel_id],
            target_states={actor_id: state for actor_id, state in self._states.items() if actor_id != vessel_id},
        )

    def step(self, commands: Mapping[int, HeadingSpeedCommand], acks: Iterable[StepAck]) -> None:
        """Advance the world by dt once all participants acknowledged."""
        unknown = sorted(set(commands) - set(self._vessels))
        if unknown:
            raise ValueError(f"Commands for vessels that are not in the scene: {unknown}")
        self.clock.advance(acks)
        reply = self._client.request({"op": "step", "commands": {str(vessel_id): [float(command.heading), float(command.speed)] for vessel_id, command in commands.items()}})
        if reply.get("index") != self.clock.index:
            raise WireError(f"the simulator at {self._client.endpoint} is at step {reply.get('index')}, the clock at {self.clock.index}")
        self._take_states(reply)

    def snapshot(self) -> Tuple[ActorState, ...]:
        """States of all actors in the order of self.actors."""
        return tuple(self._states[actor.id] for actor in self.actors)

    def close(self) -> None:
        self._client.close()

    def _take_states(self, reply: dict) -> None:
        self._states = {actor.id: ActorState(*(float(value) for value in row)) for actor, row in zip(self.actors, reply["states"])}
