"""simplify_state_path: Ramer-Douglas-Peucker thinning of a dense path for ArduPilot mission upload."""

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.asv_system.replay.path_simplification import simplify_state_path


def states(points):
    return [ActorState(x=float(x), y=float(y), speed=1.0, heading=0.0) for x, y in points]


def positions(path):
    return [(float(state.x), float(state.y)) for state in path]


def test_a_straight_run_collapses_to_its_endpoints():
    path = states((x, 0) for x in range(50))
    assert positions(simplify_state_path(path, epsilon_m=1.0)) == [(0.0, 0.0), (49.0, 0.0)]


def test_a_corner_is_kept():
    path = states([(x, 0) for x in range(10)] + [(9, y) for y in range(1, 10)])
    assert positions(simplify_state_path(path, epsilon_m=1.0)) == [(0.0, 0.0), (9.0, 0.0), (9.0, 9.0)]


def test_deviation_below_the_tolerance_is_dropped_and_above_it_kept():
    path = states([(0, 0), (5, 0.4), (10, 0)])
    assert len(simplify_state_path(path, epsilon_m=0.5)) == 2
    assert len(simplify_state_path(path, epsilon_m=0.3)) == 3


def test_first_and_last_states_are_always_kept():
    path = states([(0, 0), (1, 5), (2, 0), (3, 5), (4, 0)])
    simplified = simplify_state_path(path, epsilon_m=100.0)
    assert simplified[0] is path[0]
    assert simplified[-1] is path[-1]


def test_result_is_a_subsequence_of_the_input():
    path = states([(0, 0), (3, 1), (6, 0), (9, 4), (12, 0), (15, 1)])
    simplified = simplify_state_path(path, epsilon_m=0.5)
    indices = [path.index(state) for state in simplified]
    assert indices == sorted(indices)


@pytest.mark.parametrize("epsilon", [0.0, -1.0])
def test_non_positive_tolerance_returns_the_input_unchanged(epsilon):
    path = states((x, 0) for x in range(5))
    assert simplify_state_path(path, epsilon_m=epsilon) == path


def test_fewer_than_three_states_are_returned_unchanged():
    path = states([(0, 0), (1, 1)])
    assert simplify_state_path(path, epsilon_m=1.0) == path
    assert simplify_state_path([], epsilon_m=1.0) == []


def test_the_result_is_a_new_list():
    path = states([(0, 0), (1, 0)])
    assert simplify_state_path(path, epsilon_m=1.0) is not path


def test_closed_loop_path_keeps_its_far_point():
    path = states([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    simplified = simplify_state_path(path, epsilon_m=1.0)
    assert (10.0, 10.0) in positions(simplified)
