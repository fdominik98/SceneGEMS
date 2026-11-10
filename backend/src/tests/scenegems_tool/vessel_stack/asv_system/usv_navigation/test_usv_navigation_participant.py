"""UsvNavigationParticipant: which targets and which safety distance it hands the runtime. test_usv_navigation_frame.py covers the frame mapping."""

import math
from typing import Mapping, Optional

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_participant import UsvNavigationParticipant
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from tests.scenegems_tool.vessel_stack.scenarios import SPEED, make_vessel

SAFETY_RADIUS = 120.0
NEAR = ActorState(1000.0, 0.0, SPEED, math.pi)
FAR = ActorState(5000.0, 0.0, SPEED, math.pi)


def participant_with(horizon: Optional[float]) -> UsvNavigationParticipant:
    parameters = UsvNavigationParameters(goal=(8000.0, 0.0), speed=SPEED, safety_radius=SAFETY_RADIUS, control_horizon=60.0, horizon=horizon)
    participant = UsvNavigationParticipant(make_vessel(0, True), parameters)
    participant.start(0)
    return participant


def step(participant: UsvNavigationParticipant, targets: Mapping[int, ActorState], index: int = 0) -> dict:
    request = StepRequest(index, float(index), float(index + 1))
    participant.on_step(request, VesselStateObservation(float(index), participant.vessel, ActorState(0.0, 0.0, SPEED, 0.0), targets))
    return participant._runtime.configuration


def as_obstacle(state: ActorState) -> tuple:
    return (state.x, state.y, state.speed, state.heading)


def test_a_target_beyond_the_horizon_is_not_passed_to_the_runtime():
    assert step(participant_with(2000.0), {1: NEAR, 2: FAR})["obstacles"] == [as_obstacle(NEAR)]


def test_a_target_on_the_horizon_is_passed():
    assert step(participant_with(1000.0), {1: NEAR})["obstacles"] == [as_obstacle(NEAR)]


def test_a_target_is_passed_from_the_step_it_comes_into_view():
    participant = participant_with(2000.0)
    assert step(participant, {1: FAR})["obstacles"] == []
    assert step(participant, {1: NEAR}, index=1)["obstacles"] == [as_obstacle(NEAR)]


def test_without_a_horizon_every_target_is_passed_in_actor_order():
    assert step(participant_with(None), {2: FAR, 1: NEAR})["obstacles"] == [as_obstacle(NEAR), as_obstacle(FAR)]


def test_the_horizon_replaces_the_runtime_safety_distance():
    assert step(participant_with(9260.0), {1: NEAR})["dsafe"] == 9260.0


def test_without_a_horizon_the_safety_distance_is_upstream():
    assert step(participant_with(None), {1: NEAR})["dsafe"] == SAFETY_RADIUS + SPEED * 3.0


def test_the_horizon_leaves_the_arrival_radius_alone():
    assert step(participant_with(9260.0), {1: NEAR})["delta"] == step(participant_with(None), {1: NEAR})["delta"]
