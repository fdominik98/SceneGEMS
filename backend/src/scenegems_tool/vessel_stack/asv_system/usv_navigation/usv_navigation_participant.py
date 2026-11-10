"""USV Navigation as a lockstep participant in the caller's process, and how a run configures it.

The navigation step itself is UsvNavigator (usv_navigation_server.py, which also documents the
frame mapping): the same class answers in the USV Navigation container, so the participant here
and the container give the same heading and speed commands. This module adds what belongs to
SceneGEMS: the participant around the navigator and the start config derived from
UsvNavigationParameters.
"""

from typing import Any, Dict, List, Optional, Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server import UsvNavigator, participant_id
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_specs import USV_NAVIGATION_IN_PROCESS
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation


def usv_navigation_start_config(request: ParticipantRequest) -> Dict[str, Any]:
    """The config of the USV Navigation container's start message: the parameters of the run in wire form."""
    return start_config(_parameters(request))


def start_config(parameters: UsvNavigationParameters) -> Dict[str, Any]:
    return {"goal": list(parameters.goal), "speed": parameters.speed, "horizon": parameters.horizon, "runtime": parameters.runtime_kwargs()}


def usv_navigation_in_process(request: ParticipantRequest) -> "UsvNavigationParticipant":
    return UsvNavigationParticipant(request.vessel, _parameters(request))


def _parameters(request: ParticipantRequest) -> UsvNavigationParameters:
    if not isinstance(request.parameters, UsvNavigationParameters):
        raise ValueError(f"vessel {request.vessel.id} runs USV Navigation and needs UsvNavigationParameters (usv_navigation_parameters.parameters_for)")
    return request.parameters


class UsvNavigationParticipant:
    """Steps the navigator of one vessel every simulation step and commands heading and speed."""

    spec = USV_NAVIGATION_IN_PROCESS

    def __init__(self, vessel: ConcreteVessel, parameters: UsvNavigationParameters):
        self.vessel = vessel
        self.parameters = parameters
        self.participant_id = participant_id(vessel.id)
        self._navigator = UsvNavigator(max_angular_speed=vessel.max_angular_speed, **start_config(parameters))

    @property
    def transitions(self) -> List[Tuple[float, str, str]]:
        """(simulated time, transition, mode after it) of every transition of the automaton so far."""
        return self._navigator.transitions

    @property
    def goal_reached_at(self) -> Optional[float]:
        return self._navigator.goal_reached_at

    @property
    def _runtime(self) -> Any:
        return self._navigator._runtime

    def start(self, seed: int) -> None:
        del seed  # SyncColavRuntime has no randomness
        self._navigator.reset()

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        own = observation.own_state
        targets = [(target.x, target.y, target.speed, target.heading) for _, target in sorted(observation.target_states.items())]
        heading, speed = self._navigator.step(request.time, request.target_time - request.time, (own.x, own.y, own.speed, own.heading), targets)
        return HeadingSpeedCommand(heading=heading, speed=speed)

    def report(self) -> Dict[str, Any]:
        """The run record's part of this participant: the transitions and when the goal was reached."""
        return self._navigator.report()
