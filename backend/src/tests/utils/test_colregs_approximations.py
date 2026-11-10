"""Visibility distances: two vessels are in sight when either one sees the other."""

from utils.colregs_approximations import o2VisibilityByo1, possible_vis_distances_by_bearing, possible_vis_distances_by_length, vis_distance, vis_distance_with_obstacle
from utils.global_constants import VISIBILITY_DIST_2, VISIBILITY_DIST_3, VISIBILITY_DIST_5, VISIBILITY_DIST_6

SMALL, LARGE = 30.0, 100.0


def test_a_vessel_is_visible_further_from_ahead_than_from_astern():
    assert o2VisibilityByo1(False, SMALL) == VISIBILITY_DIST_5
    assert o2VisibilityByo1(True, SMALL) == VISIBILITY_DIST_2


def test_the_more_visible_vessel_sets_the_distance_of_the_pair():
    assert vis_distance(False, SMALL, False, LARGE) == VISIBILITY_DIST_6
    assert vis_distance(False, LARGE, False, SMALL) == VISIBILITY_DIST_6, "the order of the vessels does not matter"


def test_a_pair_is_in_sight_at_the_bow_range_when_only_one_vessel_sees_a_stern():
    assert vis_distance(True, SMALL, False, SMALL) == VISIBILITY_DIST_5
    assert vis_distance(False, SMALL, True, SMALL) == VISIBILITY_DIST_5


def test_two_vessels_seeing_each_others_stern_are_in_sight_at_the_stern_range():
    assert vis_distance(True, SMALL, True, LARGE) == VISIBILITY_DIST_3


def test_a_pair_with_a_static_obstacle_keeps_the_shorter_range():
    assert vis_distance_with_obstacle(False, SMALL, False, LARGE) == VISIBILITY_DIST_5


def test_possible_distances_by_length_take_the_longer_range_of_each_bearing_combination():
    assert possible_vis_distances_by_length(SMALL, LARGE) == [VISIBILITY_DIST_3, VISIBILITY_DIST_6, VISIBILITY_DIST_5, VISIBILITY_DIST_6]


def test_possible_distances_by_bearing_are_the_stern_ranges_only_when_both_vessels_see_a_stern():
    stern_ranges = {VISIBILITY_DIST_2, VISIBILITY_DIST_3}
    every_range = stern_ranges | {VISIBILITY_DIST_5, VISIBILITY_DIST_6}
    assert set(possible_vis_distances_by_bearing(True, True)) == stern_ranges
    assert set(possible_vis_distances_by_bearing(True, False)) == every_range
    assert set(possible_vis_distances_by_bearing(False, True)) == every_range
    assert set(possible_vis_distances_by_bearing(False, False)) == every_range
