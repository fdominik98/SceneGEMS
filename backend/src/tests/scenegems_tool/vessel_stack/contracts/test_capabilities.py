"""Capabilities: defaults mean no limit, and a chain is the weakest link over its specs."""

import math

import pytest

from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.capabilities import (
    ALL_STEERING_TYPES,
    Capabilities,
    EnvironmentSupport,
    RepeatabilityTier,
    steering_type_text,
    steering_type_values,
    weaker_support,
    weaker_tier,
    weakest_link,
)


class TestDefaults:
    def test_a_default_spec_sets_no_limit(self):
        capabilities = Capabilities()
        assert capabilities.faster_than_real_time and capabilities.lockstep
        assert capabilities.repeatability_tier == RepeatabilityTier.EXACT
        assert capabilities.wind == capabilities.waves == EnvironmentSupport.SUPPORTED
        assert math.isinf(capabilities.max_speedup)
        assert not capabilities.interactive_only

    def test_speedup_limit_is_one_when_not_faster_than_real_time(self):
        assert Capabilities(faster_than_real_time=False, max_speedup=50).speedup_limit == 1.0

    def test_speedup_limit_is_the_max_speedup_otherwise(self):
        assert Capabilities(max_speedup=50).speedup_limit == 50
        assert Capabilities(max_speedup=None).speedup_limit is None

    def test_as_dict_uses_plain_values(self):
        data = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, wind=EnvironmentSupport.UNMEASURED).as_dict()
        assert data["repeatability_tier"] == "bounded"
        assert data["wind"] == "unmeasured"
        assert data["lockstep"] is True


class TestSteeringTypes:
    def test_a_default_spec_runs_every_steering_type(self):
        assert Capabilities().steering_types == ALL_STEERING_TYPES == {SteeringType.RUDDER, SteeringType.SKID, SteeringType.VECTORED_THRUST}

    def test_steering_types_are_given_as_types_or_as_their_names(self):
        assert Capabilities(steering_types={"rudder", SteeringType.SKID}).steering_types == frozenset({SteeringType.RUDDER, SteeringType.SKID})

    def test_an_unknown_steering_type_is_rejected(self):
        with pytest.raises(ValueError):
            Capabilities(steering_types={"sail"})

    def test_a_chain_runs_the_steering_types_all_its_specs_run(self):
        rudder_and_skid = Capabilities(steering_types={SteeringType.RUDDER, SteeringType.SKID})
        skid_and_vectored = Capabilities(steering_types={SteeringType.SKID, SteeringType.VECTORED_THRUST})
        assert Capabilities().combine(rudder_and_skid).steering_types == rudder_and_skid.steering_types
        assert rudder_and_skid.combine(skid_and_vectored).steering_types == {SteeringType.SKID}
        assert rudder_and_skid.combine(skid_and_vectored) == skid_and_vectored.combine(rudder_and_skid)
        assert weakest_link([Capabilities(), rudder_and_skid, skid_and_vectored]).steering_types == {SteeringType.SKID}

    def test_specs_with_no_steering_type_in_common_leave_none(self):
        combined = Capabilities(steering_types={SteeringType.RUDDER}).combine(Capabilities(steering_types={SteeringType.SKID}))
        assert combined.steering_types == frozenset()
        assert combined.as_dict()["steering_types"] == []

    def test_as_dict_lists_the_names_in_the_order_of_the_steering_types(self):
        assert Capabilities().as_dict()["steering_types"] == ["rudder", "skid", "vectored_thrust"]
        assert Capabilities(steering_types={SteeringType.VECTORED_THRUST, SteeringType.RUDDER}).as_dict()["steering_types"] == ["rudder", "vectored_thrust"]
        assert steering_type_values({SteeringType.SKID, SteeringType.RUDDER}) == ["rudder", "skid"]

    def test_steering_types_in_words(self):
        assert steering_type_text(ALL_STEERING_TYPES) == "rudder, skid and vectored thrust"
        assert steering_type_text({SteeringType.SKID, SteeringType.RUDDER}) == "rudder and skid"
        assert steering_type_text([SteeringType.VECTORED_THRUST]) == "vectored thrust"
        assert steering_type_text([]) == "no steering type"

    def test_capabilities_stay_hashable(self):
        assert len({Capabilities(), Capabilities(steering_types=set(SteeringType)), Capabilities(steering_types={"skid"})}) == 2


class TestOrdering:
    @pytest.mark.parametrize(
        "first,second,expected",
        [
            (RepeatabilityTier.EXACT, RepeatabilityTier.BOUNDED, RepeatabilityTier.BOUNDED),
            (RepeatabilityTier.BOUNDED, RepeatabilityTier.EXACT, RepeatabilityTier.BOUNDED),
            (RepeatabilityTier.NONE, RepeatabilityTier.EXACT, RepeatabilityTier.NONE),
            (RepeatabilityTier.BOUNDED, RepeatabilityTier.NONE, RepeatabilityTier.NONE),
            (RepeatabilityTier.EXACT, RepeatabilityTier.EXACT, RepeatabilityTier.EXACT),
        ],
    )
    def test_weaker_tier(self, first, second, expected):
        assert weaker_tier(first, second) == expected

    @pytest.mark.parametrize(
        "first,second,expected",
        [
            (EnvironmentSupport.SUPPORTED, EnvironmentSupport.UNMEASURED, EnvironmentSupport.UNMEASURED),
            (EnvironmentSupport.UNMEASURED, EnvironmentSupport.UNSUPPORTED, EnvironmentSupport.UNSUPPORTED),
            (EnvironmentSupport.SUPPORTED, EnvironmentSupport.UNSUPPORTED, EnvironmentSupport.UNSUPPORTED),
            (EnvironmentSupport.SUPPORTED, EnvironmentSupport.SUPPORTED, EnvironmentSupport.SUPPORTED),
        ],
    )
    def test_weaker_support(self, first, second, expected):
        assert weaker_support(first, second) == expected
        assert weaker_support(second, first) == expected


class TestRepeatabilityAt:
    def test_bounded_stack_is_exact_up_to_its_limit(self):
        capabilities = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=1)
        assert capabilities.repeatability_at(1) == RepeatabilityTier.EXACT
        assert capabilities.repeatability_at(1.5) == RepeatabilityTier.BOUNDED

    def test_without_a_limit_the_tier_applies_everywhere(self):
        assert Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED).repeatability_at(1) == RepeatabilityTier.BOUNDED


class TestCombine:
    def test_flags_are_and_ed(self):
        combined = Capabilities(lockstep=False).combine(Capabilities(faster_than_real_time=False))
        assert not combined.lockstep
        assert not combined.faster_than_real_time

    def test_interactive_only_is_or_ed(self):
        assert Capabilities().combine(Capabilities(interactive_only=True)).interactive_only
        assert Capabilities(interactive_only=True).combine(Capabilities()).interactive_only

    def test_max_speedup_is_the_minimum(self):
        assert Capabilities(max_speedup=100).combine(Capabilities(max_speedup=50)).max_speedup == 50
        assert Capabilities(max_speedup=100).combine(Capabilities()).max_speedup == 100

    def test_an_unmeasured_speedup_stays_unmeasured(self):
        assert Capabilities(max_speedup=None).combine(Capabilities(max_speedup=50)).max_speedup is None
        assert Capabilities(max_speedup=50).combine(Capabilities(max_speedup=None)).max_speedup is None

    def test_environment_support_takes_the_weaker_side(self):
        combined = Capabilities(wind=EnvironmentSupport.UNMEASURED, waves=EnvironmentSupport.SUPPORTED).combine(Capabilities(wind=EnvironmentSupport.SUPPORTED, waves=EnvironmentSupport.UNSUPPORTED))
        assert combined.wind == EnvironmentSupport.UNMEASURED
        assert combined.waves == EnvironmentSupport.UNSUPPORTED

    def test_exact_with_exact_stays_exact_and_has_no_exact_limit(self):
        combined = Capabilities().combine(Capabilities())
        assert combined.repeatability_tier == RepeatabilityTier.EXACT
        assert combined.exact_up_to_speedup is None

    def test_exact_limit_survives_combination_with_an_exact_spec(self):
        bounded = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=1)
        combined = Capabilities().combine(bounded)
        assert combined.repeatability_tier == RepeatabilityTier.BOUNDED
        assert combined.exact_up_to_speedup == 1

    def test_the_smaller_of_two_exact_limits_wins(self):
        first = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=5)
        second = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=2)
        assert first.combine(second).exact_up_to_speedup == 2

    def test_a_bounded_spec_without_exact_range_removes_it(self):
        first = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=5)
        second = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED)
        assert first.combine(second).exact_up_to_speedup is None

    def test_combination_is_symmetric(self):
        first = Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, exact_up_to_speedup=3, max_speedup=20, wind=EnvironmentSupport.UNMEASURED)
        second = Capabilities(lockstep=False, max_speedup=50, waves=EnvironmentSupport.UNSUPPORTED)
        assert first.combine(second) == second.combine(first)

    def test_weakest_link_of_nothing_is_the_default(self):
        assert weakest_link([]) == Capabilities()

    def test_weakest_link_over_a_chain(self):
        chain = [Capabilities(), Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED, max_speedup=100), Capabilities(lockstep=False, max_speedup=50)]
        result = weakest_link(chain)
        assert result.repeatability_tier == RepeatabilityTier.BOUNDED
        assert result.max_speedup == 50
        assert not result.lockstep
