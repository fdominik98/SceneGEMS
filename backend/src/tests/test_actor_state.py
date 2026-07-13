import math
import unittest

import numpy as np

from concrete_level.models.actor_state import ActorState


class TestActorStateSpatialRelationships(unittest.TestCase):
    """Test cases for ActorState spatial relationship methods."""

    def test_left_of_heading_east(self):
        """Test when actor is to the left of other who is heading east."""
        # Other actor at (5, -5) heading east
        other = ActorState(x=5, y=-5, speed=10, heading=0)

        # Actor to the north (left side of other from other's perspective)
        actor_left = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_left.left_of(other))

        # Actor to the south (right side of other from other's perspective)
        actor_right = ActorState(x=5, y=-10, speed=10, heading=0)
        self.assertFalse(actor_right.left_of(other))

    def test_left_of_heading_north(self):
        """Test when actor is to the left of other who is heading north."""
        # Other actor at (5, 5) heading north
        other = ActorState(x=5, y=5, speed=10, heading=math.pi / 2)

        # Actor to the west (left side of other from other's perspective)
        actor_left = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_left.left_of(other))

        # Actor to the east (right side of other from other's perspective)
        actor_right = ActorState(x=10, y=5, speed=10, heading=0)
        self.assertFalse(actor_right.left_of(other))

    def test_left_of_heading_west(self):
        """Test when actor is to the left of other who is heading west."""
        # Other actor at (-5, 5) heading west
        other = ActorState(x=-5, y=5, speed=10, heading=math.pi)

        # Actor to the south (left side of other from other's perspective)
        actor_left = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_left.left_of(other))

        # Actor to the north (right side of other from other's perspective)
        actor_right = ActorState(x=-5, y=10, speed=10, heading=0)
        self.assertFalse(actor_right.left_of(other))

    def test_left_of_heading_south(self):
        """Test when actor is to the left of other who is heading south."""
        # Other actor at (-5, -5) heading south
        other = ActorState(x=-5, y=-5, speed=10, heading=-math.pi / 2)

        # Actor to the east (left side of other from other's perspective)
        actor_left = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_left.left_of(other))

        # Actor to the west (right side of other from other's perspective)
        actor_right = ActorState(x=-10, y=-5, speed=10, heading=0)
        self.assertFalse(actor_right.left_of(other))

    def test_left_of_diagonal_heading(self):
        """Test when actor is to the left of other who is heading northeast."""
        # Other actor at (5, -1) heading northeast
        other = ActorState(x=5, y=-1, speed=10, heading=math.pi / 4)

        # Actor to the northwest (left side of other from other's perspective)
        actor_left = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_left.left_of(other))

        # Actor to the southeast (right side of other from other's perspective)
        actor_right = ActorState(x=8, y=-4, speed=10, heading=0)
        self.assertFalse(actor_right.left_of(other))

    def test_right_of_heading_east(self):
        """Test when actor is to the right of other who is heading east."""
        # Other actor at (5, 5) heading east
        other = ActorState(x=5, y=5, speed=10, heading=0)

        # Actor to the south (right side of other from other's perspective)
        actor_right = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_right.right_of(other))

        # Actor to the north (left side of other from other's perspective)
        actor_left = ActorState(x=5, y=10, speed=10, heading=0)
        self.assertFalse(actor_left.right_of(other))

    def test_right_of_heading_north(self):
        """Test when actor is to the right of other who is heading north."""
        # Other actor at (-5, 5) heading north
        other = ActorState(x=-5, y=5, speed=10, heading=math.pi / 2)

        # Actor to the east (right side of other from other's perspective)
        actor_right = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_right.right_of(other))

        # Actor to the west (left side of other from other's perspective)
        actor_left = ActorState(x=-10, y=5, speed=10, heading=0)
        self.assertFalse(actor_left.right_of(other))

    def test_right_of_heading_west(self):
        """Test when actor is to the right of other who is heading west."""
        # Other actor at (-5, -5) heading west
        other = ActorState(x=-5, y=-5, speed=10, heading=math.pi)

        # Actor to the north (right side of other from other's perspective)
        actor_right = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_right.right_of(other))

        # Actor to the south (left side of other from other's perspective)
        actor_left = ActorState(x=-5, y=-10, speed=10, heading=0)
        self.assertFalse(actor_left.right_of(other))

    def test_right_of_heading_south(self):
        """Test when actor is to the right of other who is heading south."""
        # Other actor at (5, -5) heading south
        other = ActorState(x=5, y=-5, speed=10, heading=-math.pi / 2)

        # Actor to the west (right side of other from other's perspective)
        actor_right = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_right.right_of(other))

        # Actor to the east (left side of other from other's perspective)
        actor_left = ActorState(x=10, y=-5, speed=10, heading=0)
        self.assertFalse(actor_left.right_of(other))

    def test_right_of_diagonal_heading(self):
        """Test when actor is to the right of other who is heading northeast."""
        # Other actor at (-1, 5) heading northeast
        other = ActorState(x=-1, y=5, speed=10, heading=math.pi / 4)

        # Actor to the southeast (right side of other from other's perspective)
        actor_right = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_right.right_of(other))

        # Actor to the northwest (left side of other from other's perspective)
        actor_left = ActorState(x=-4, y=8, speed=10, heading=0)
        self.assertFalse(actor_left.right_of(other))

    def test_behind_heading_east(self):
        """Test when actor is behind other who is heading east."""
        # Other actor at origin heading east
        other = ActorState(x=0, y=0, speed=10, heading=0)

        # Actor to the east (behind other from other's perspective)
        actor_behind_other = ActorState(x=-5, y=0, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the west (in front of other from other's perspective)
        actor_front_other = ActorState(x=5, y=0, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_behind_heading_north(self):
        """Test when actor is behind other who is heading north."""
        # Other actor at origin heading north
        other = ActorState(x=0, y=0, speed=10, heading=math.pi / 2)

        # Actor to the north (behind other from other's perspective)
        actor_behind_other = ActorState(x=0, y=-5, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the south (in front of other from other's perspective)
        actor_front_other = ActorState(x=0, y=5, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_behind_heading_west(self):
        """Test when actor is behind other who is heading west."""
        # Other actor at origin heading west
        other = ActorState(x=0, y=0, speed=10, heading=math.pi)

        # Actor to the east (behind other from other's perspective)
        actor_behind_other = ActorState(x=5, y=0, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the west (in front of other from other's perspective)
        actor_front_other = ActorState(x=-5, y=0, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_behind_heading_south(self):
        """Test when actor is behind other who is heading south."""
        # Other actor at origin heading south
        other = ActorState(x=0, y=0, speed=10, heading=-math.pi / 2)

        # Actor to the north (behind other from other's perspective)
        actor_behind_other = ActorState(x=0, y=5, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the south (in front of other from other's perspective)
        actor_front_other = ActorState(x=0, y=-5, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_behind_diagonal_heading(self):
        """Test when actor is behind other who is heading northeast."""
        # Other actor at origin heading northeast
        other = ActorState(x=5, y=5, speed=10, heading=math.pi / 4)

        # Actor to the northeast (behind other from other's perspective)
        actor_behind_other = ActorState(x=0, y=0, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the southwest (in front of other from other's perspective)
        actor_front_other = ActorState(x=10, y=10, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_behind_with_offset(self):
        """Test when actor is behind other at non-origin positions."""
        # Other actor at (10, 10) heading east
        other = ActorState(x=10, y=10, speed=10, heading=0)

        # Actor to the east (behind other from other's perspective)
        actor_behind_other = ActorState(x=5, y=12, speed=10, heading=0)
        self.assertTrue(actor_behind_other.behind(other))

        # Actor to the west (in front of other from other's perspective)
        actor_front_other = ActorState(x=15, y=8, speed=10, heading=0)
        self.assertFalse(actor_front_other.behind(other))

    def test_in_front_of_heading_east(self):
        """Test when actor is in front of other who is heading east."""
        # Other actor at origin heading east
        other = ActorState(x=0, y=0, speed=10, heading=0)

        # Actor to the east (in front of other from other's perspective)
        actor_front_other = ActorState(x=5, y=0, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))

        # Actor to the west (behind other from other's perspective)
        actor_behind_other = ActorState(x=-5, y=0, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))

    def test_in_front_of_heading_north(self):
        """Test when actor is in front of other who is heading north."""
        # Other actor at origin heading north
        other = ActorState(x=0, y=0, speed=10, heading=math.pi / 2)

        # Actor to the south (in front of other from other's perspective)
        actor_front_other = ActorState(x=0, y=5, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))

        # Actor to the north (behind other from other's perspective)
        actor_behind_other = ActorState(x=0, y=-5, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))

    def test_in_front_of_heading_west(self):
        """Test when actor is in front of other who is heading west."""
        # Other actor at origin heading west
        other = ActorState(x=0, y=0, speed=10, heading=math.pi)

        # Actor to the east (in front of other from other's perspective)
        actor_front_other = ActorState(x=-5, y=0, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))
        self.assertTrue(other.in_front_of(actor_front_other))

        # Actor to the west (behind other from other's perspective)
        actor_behind_other = ActorState(x=5, y=0, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))
        self.assertTrue(other.behind(actor_behind_other))

    def test_in_front_of_heading_south(self):
        """Test when actor is in front of other who is heading south."""
        # Other actor at origin heading south
        other = ActorState(x=0, y=0, speed=10, heading=-math.pi / 2)

        # Actor to the north (in front of other from other's perspective)
        actor_front_other = ActorState(x=0, y=-5, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))

        # Actor to the south (behind other from other's perspective)
        actor_behind_other = ActorState(x=0, y=5, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))

    def test_in_front_of_diagonal_heading(self):
        """Test when actor is in front of other who is heading northeast."""
        # Other actor at origin heading northeast
        other = ActorState(x=0, y=0, speed=10, heading=math.pi / 4)

        # Actor to the north-east (in front of other from other's perspective)
        actor_front_other = ActorState(x=5, y=5, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))

        # Actor to the south-west (behind other from other's perspective)
        actor_behind_other = ActorState(x=-5, y=-5, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))

    def test_in_front_of_with_offset(self):
        """Test when actor is in front of other at non-origin positions."""
        # Other actor at (10, 10) heading east
        other = ActorState(x=10, y=10, speed=10, heading=0)

        # Actor to the east (in front of other from other's perspective)
        actor_front_other = ActorState(x=15, y=12, speed=10, heading=0)
        self.assertTrue(actor_front_other.in_front_of(other))

        # Actor to the west (behind other from other's perspective)
        actor_behind_other = ActorState(x=8, y=8, speed=10, heading=0)
        self.assertFalse(actor_behind_other.in_front_of(other))

    def test_edge_case_same_position(self):
        """Test edge case when both actors are at the same position."""
        actor = ActorState(x=5, y=5, speed=10, heading=0)
        other = ActorState(x=5, y=5, speed=10, heading=math.pi / 2)

        # When at the same position, all spatial relationships should be False
        # actor is neither left, right, in front, nor behind other
        self.assertFalse(actor.left_of(other))
        self.assertFalse(actor.right_of(other))
        self.assertFalse(actor.behind(other))
        self.assertFalse(actor.in_front_of(other))

    def test_edge_case_directly_right(self):
        """Test edge case when actor is exactly to the right of other (perpendicular)."""
        # Other actor heading east at origin
        other = ActorState(x=0, y=0, speed=10, heading=0)

        # Actor directly to the south (90 degrees to the right of other)
        actor = ActorState(x=0, y=-5, speed=10, heading=0)

        # actor is to the right of other, not left, not in front, not behind
        self.assertFalse(actor.left_of(other))
        self.assertTrue(actor.right_of(other))
        self.assertFalse(actor.behind(other))
        self.assertFalse(actor.in_front_of(other))

    def test_edge_case_directly_left(self):
        """Test edge case when actor is exactly to the left of other (perpendicular)."""
        # Other actor heading east at origin
        other = ActorState(x=0, y=0, speed=10, heading=0)

        # Actor directly to the north (90 degrees to the left of other)
        actor = ActorState(x=0, y=5, speed=10, heading=0)

        # actor is to the left of other, not right, not in front, not behind
        self.assertTrue(actor.left_of(other))
        self.assertFalse(actor.right_of(other))
        self.assertFalse(actor.behind(other))
        self.assertFalse(actor.in_front_of(other))

    def test_combined_spatial_relationships(self):
        """Test combined spatial relationships (front/back with left/right)."""
        # Other actor heading east at origin
        other = ActorState(x=0, y=0, speed=10, heading=0)

        actor_in_front_right = ActorState(x=5, y=-3, speed=10, heading=0)
        self.assertTrue(actor_in_front_right.in_front_of(other))
        self.assertTrue(actor_in_front_right.right_of(other))
        self.assertFalse(actor_in_front_right.left_of(other))
        self.assertFalse(actor_in_front_right.behind(other))

        actor_behind_left = ActorState(x=-5, y=3, speed=10, heading=0)
        self.assertTrue(actor_behind_left.behind(other))
        self.assertTrue(actor_behind_left.left_of(other))
        self.assertFalse(actor_behind_left.right_of(other))
        self.assertFalse(actor_behind_left.in_front_of(other))


if __name__ == "__main__":
    unittest.main()
