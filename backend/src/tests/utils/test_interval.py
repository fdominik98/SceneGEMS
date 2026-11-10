"""Interval: a union of closed parts and cropping a value onto it."""

import pytest

from utils.interval import Interval

# The legal heading steps of a seed vessel: turn hard to either side or stay inside the dead zone.
STEPS = Interval(Interval.closed(-45.0, -6.5), Interval.closed(-2.0, 2.0), Interval.closed(6.5, 45.0))


class TestCrop:
    @pytest.mark.parametrize("value", [-45.0, -10.0, 0.0, 2.0, 30.0])
    def test_a_value_inside_a_part_stays(self, value):
        assert STEPS.crop(value) == value

    @pytest.mark.parametrize("value, expected", [(2.2, 2.0), (-2.2, -2.0), (4.0, 2.0), (-4.0, -2.0)])
    def test_a_value_just_outside_the_dead_zone_goes_to_its_near_bound(self, value, expected):
        """2.2 used to become -2: the heading stepped away from its target and never settled."""
        assert STEPS.crop(value) == expected

    @pytest.mark.parametrize("value, expected", [(5.0, 6.5), (-5.0, -6.5)])
    def test_a_value_closer_to_the_next_part_goes_there(self, value, expected):
        assert STEPS.crop(value) == expected

    @pytest.mark.parametrize("value, expected", [(90.0, 45.0), (-90.0, -45.0)])
    def test_a_value_beyond_every_part_goes_to_the_outermost_bound(self, value, expected):
        assert STEPS.crop(value) == expected

    def test_a_single_part_crops_to_its_own_bounds(self):
        part = Interval.closed(1.0, 3.0)
        assert (part.crop(0.0), part.crop(2.0), part.crop(9.0)) == (1.0, 2.0, 3.0)

    def test_an_empty_interval_cannot_crop(self):
        with pytest.raises(ValueError):
            Interval().crop(1.0)


def test_closed_builds_an_interval_with_both_bounds_inside():
    part = Interval.closed(-1.0, 1.0)
    assert isinstance(part, Interval)
    assert part.contains(-1.0) and part.contains(1.0) and not part.contains(1.5)
