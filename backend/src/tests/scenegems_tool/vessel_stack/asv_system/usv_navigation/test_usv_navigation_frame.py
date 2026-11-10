"""Frame test of the USV Navigation adapter: head-on and crossing encounters on the kinematic layer.

SceneGEMS uses x east, y north and a heading in radians counterclockwise from east. The
adapter passes these to SyncColavRuntime unchanged (design doc 12.9). These tests pin that
mapping through observable behaviour, so an axis swap, a compass heading or a flipped turn
sense fails here:

- the runtime classifies each encounter as SceneGEMS defines it;
- a goal behind the left beam is reached, which a compass heading would miss;
- avoidance turns clockwise (to starboard) in the head-on case and in the crossing from
  starboard, and the crossing from port is its exact mirror image.
"""

import math

import numpy as np
import pytest
from colav_automaton.guards.conditions import classify_encounter

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_participant import UsvNavigationParticipant
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import KinematicRunResult, run_kinematic_closed_loop, run_lockstep
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation
from tests.scenegems_tool.vessel_stack.scenarios import ENCOUNTER_TARGETS, SPEED, encounter_trajectories, make_vessel

STEPS = 1000
AVOIDANCE = ("head_on", "crossing_from_starboard", "crossing_from_port")


@pytest.fixture(scope="module")
def runs():
    return {name: run_kinematic_closed_loop(encounter_trajectories(name, STEPS)) for name in ENCOUNTER_TARGETS}


def own_track(result: KinematicRunResult):
    index = [actor.id for actor in result.actors].index(0)
    states = [step[index] for step in result.states]
    return np.array([state.x for state in states]), np.array([state.y for state in states]), np.unwrap([state.heading for state in states])


def heading_change_degrees(result: KinematicRunResult):
    _, _, heading = own_track(result)
    return math.degrees(float((heading - heading[0]).min())), math.degrees(float((heading - heading[0]).max()))


def separation(result: KinematicRunResult) -> np.ndarray:
    own_index = [actor.id for actor in result.actors].index(0)
    other_index = 1 - own_index
    return np.array([math.hypot(step[own_index].x - step[other_index].x, step[own_index].y - step[other_index].y) for step in result.states])


class TestRuntimeClassifiesEncountersLikeSceneGEMS:
    @pytest.mark.parametrize("name,expected", [("head_on", "head_on"), ("crossing_from_starboard", "crossing_from_starboard"), ("crossing_from_port", "crossing_from_port")])
    def test_classification(self, name, expected):
        scene = encounter_trajectories(name, 1).initial_scene
        own = scene.os_state
        target = scene[scene.actors[1]]
        assert classify_encounter(own.heading, [(target.x, target.y, target.speed, target.heading)], own.x, own.y) == expected

    def test_a_target_ahead_on_the_same_course_is_called_crossing_from_starboard_by_upstream(self):
        # Upstream calls traffic overtaking only when it is behind, so this label is the
        # runtime's own and is not used by the guards (design doc 12.9). Pinned so a change
        # of the upstream classifier shows up.
        scene = encounter_trajectories("overtaking", 1).initial_scene
        own = scene.os_state
        target = scene[scene.actors[1]]
        assert classify_encounter(own.heading, [(target.x, target.y, target.speed, target.heading)], own.x, own.y) == "crossing_from_starboard"


class TestAxisAndHeadingConvention:
    @pytest.mark.parametrize("goal", [(-3000.0, 5000.0), (3000.0, -5000.0), (5000.0, 5000.0), (-5000.0, -2000.0)])
    def test_goal_off_the_bow_is_reached(self, goal):
        own = make_vessel(0, True)
        scene_states = {own: ActorState(0.0, 0.0, SPEED, 0.0)}
        from concrete_level.models.concrete_scene import ConcreteScene

        parameters = UsvNavigationParameters(goal=goal, speed=SPEED, safety_radius=120.0, control_horizon=2 * math.pi / own.max_angular_speed)
        participant = UsvNavigationParticipant(own, parameters)
        simulation = KinematicSimulation(ConcreteScene(scene_states), 1.0, [participant.participant_id])
        result = run_lockstep(simulation, {own.id: participant}, 1500, 0)
        assert participant.goal_reached_at is not None
        arrival = result.states[int(participant.goal_reached_at)][0]  # after arrival the vessel holds course and sails on
        assert math.hypot(goal[0] - arrival.x, goal[1] - arrival.y) < 50.0

    def test_heading_pi_over_two_is_north_not_east(self):
        # The upstream plant moves x with cos(psi) and y with sin(psi); the kinematic layer
        # must agree, or the avoidance in the other tests would run mirrored.
        own = make_vessel(0, True)
        from concrete_level.models.concrete_scene import ConcreteScene

        simulation = KinematicSimulation(ConcreteScene({own: ActorState(0.0, 0.0, SPEED, math.pi / 2)}), 1.0, [])
        simulation.step({}, [])
        state = simulation.snapshot()[0]
        assert state.x == pytest.approx(0.0, abs=1e-9)
        assert state.y == pytest.approx(SPEED)

    @pytest.mark.parametrize("name", AVOIDANCE)
    def test_avoidance_starts_in_the_middle_of_the_encounter(self, runs, name):
        transitions = runs[name].run_record["usv_navigation"]["transitions"]
        assert transitions[0][1] == "avoid"
        assert transitions[0][2] == "COLLISION_AVOIDANCE"
        assert 100 < transitions[0][0] < 300

    @pytest.mark.parametrize("name", AVOIDANCE)
    def test_avoidance_ends_with_a_resume(self, runs, name):
        transitions = runs[name].run_record["usv_navigation"]["transitions"]
        assert [transition for _, transition, _ in transitions] == ["avoid", "hold", "resume"]


class TestStarboardIsClockwise:
    def test_head_on_first_turns_to_starboard(self, runs):
        _, _, heading = own_track(runs["head_on"])
        avoid_at = int(runs["head_on"].run_record["usv_navigation"]["transitions"][0][0])
        assert heading[avoid_at + 30] - heading[avoid_at] < 0
        assert math.degrees(float(np.min(heading - heading[0]))) == pytest.approx(-5.5, abs=0.1)

    def test_head_on_passes_with_the_target_on_the_port_side(self, runs):
        result = runs["head_on"]
        own_x, own_y, _ = own_track(result)
        closest = int(np.argmin(separation(result)))
        assert own_y[closest] < 0.0, "the own ship passes to the south of the line, which is to starboard when heading east"

    def test_head_on_clearance_matches_the_recorded_integration_result(self, runs):
        assert float(separation(runs["head_on"]).min()) == pytest.approx(146.3, abs=0.5)

    def test_crossing_from_starboard_gives_way_by_turning_clockwise(self, runs):
        low, high = heading_change_degrees(runs["crossing_from_starboard"])
        assert low == pytest.approx(-53.0, abs=0.2)
        assert high == pytest.approx(25.6, abs=0.2)

    def test_crossing_from_starboard_passes_behind_the_target(self, runs):
        result = runs["crossing_from_starboard"]
        assert float(separation(result).min()) == pytest.approx(945.1, abs=0.5)

    def test_crossing_from_port_is_the_exact_mirror_of_crossing_from_starboard(self, runs):
        starboard_x, starboard_y, starboard_heading = own_track(runs["crossing_from_starboard"])
        port_x, port_y, port_heading = own_track(runs["crossing_from_port"])
        np.testing.assert_allclose(port_x, starboard_x, atol=1e-6)
        np.testing.assert_allclose(port_y, -starboard_y, atol=1e-6)
        np.testing.assert_allclose(port_heading, -starboard_heading, atol=1e-9)
        assert runs["crossing_from_port"].run_record["usv_navigation"]["transitions"] == runs["crossing_from_starboard"].run_record["usv_navigation"]["transitions"]

    def test_overtaking_passes_the_slower_target_to_starboard(self, runs):
        result = runs["overtaking"]
        _, own_y, _ = own_track(result)
        closest = int(np.argmin(separation(result)))
        assert own_y[closest] < 0.0
        assert float(separation(result).min()) == pytest.approx(165.4, abs=0.5)
