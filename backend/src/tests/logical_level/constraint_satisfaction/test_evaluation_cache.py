"""GeometricProperties.vis_distance: the range at which a pair counts as in sight."""

import math

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from utils.global_constants import VISIBILITY_DIST_2, VISIBILITY_DIST_5, VISIBILITY_DIST_6

SPEED = 8.0
SMALL = make_vessel(0, True, length=30.0)
LARGE = make_vessel(1, False, length=100.0)
OBSTACLE = ConcreteActor.from_dict({"id": 2, "type": "SmallIsland", "length": 30.0, "safety_radius": 30.0, "is_vessel": False})


def test_two_vessels_meeting_are_in_sight_from_the_range_of_the_more_visible_one():
    scene = ConcreteScene({SMALL: ActorState(0.0, 0.0, SPEED, 0.0), LARGE: ActorState(5000.0, 0.0, SPEED, math.pi)})
    assert scene.get_geo_props(SMALL, LARGE).vis_distance == VISIBILITY_DIST_6
    assert scene.get_geo_props(LARGE, SMALL).vis_distance == VISIBILITY_DIST_6


def test_an_overtaking_pair_is_in_sight_from_the_range_the_vessel_ahead_sees_the_other_at():
    # Same course, the target astern of the own ship: the target sees a sternlight
    # (2 nm), the own ship sees the target's bow (5 nm). One direction is enough.
    target = make_vessel(1, False, length=30.0)
    scene = ConcreteScene({SMALL: ActorState(0.0, 0.0, SPEED, 0.0), target: ActorState(-5000.0, 0.0, SPEED, 0.0)})
    assert VISIBILITY_DIST_2 < scene.get_geo_props(SMALL, target).vis_distance == VISIBILITY_DIST_5


def test_a_static_obstacle_does_not_extend_the_range_of_its_pair():
    scene = ConcreteScene({LARGE: ActorState(0.0, 0.0, SPEED, 0.0), OBSTACLE: ActorState(3000.0, 0.0, 0.0, 0.0)})
    assert scene.get_geo_props(LARGE, OBSTACLE).vis_distance == VISIBILITY_DIST_5
    assert scene.get_geo_props(OBSTACLE, LARGE).vis_distance == VISIBILITY_DIST_5
