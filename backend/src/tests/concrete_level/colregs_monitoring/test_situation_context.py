"""SituationContext: the potential collision domain of a pair, predicted on the courses it is steering."""

import math
from typing import List

from concrete_level.colregs_monitoring.situation_context import COLREGSType, CrossingFromPortSituationContext, OtherSituationContext, SituationContext
from concrete_level.colregs_monitoring.situation_context_state_machine import SituationContextStateMachine
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.maneuvering_domain import ManeuveringDomain
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, TARGET, constants

# The own ship heads east from the origin, the target heads north from 4 km ahead and
# 4 km to starboard, both at the same speed: they meet at (4000, 0) and the own ship
# gives way. At 8 m/s that is 500 s off, at 2 m/s 2000 s, beyond the safe temporal
# distance of 1200 s.
NEAR_SPEED, FAR_SPEED = 8.0, 2.0
NEAR_TCPA, FAR_TCPA = 500.0, 2000.0


def crossing(speed: float, target_x: float = 4000.0) -> ConcreteScene:
    return ConcreteScene({OWN_SHIP: ActorState(0.0, 0.0, speed, 0.0), TARGET: ActorState(target_x, -4000.0, speed, math.pi / 2)})


def encounter(scene: ConcreteScene) -> SituationContext:
    return SituationContextStateMachine.create_initial(scene, OWN_SHIP, TARGET, 0, constants())


def violation_times(context: SituationContext) -> List[float]:
    return context.domain_violation_times(context.start_scene[context.actor1], context.start_scene[context.actor2])


def test_the_test_geometry_is_a_crossing_the_own_ship_gives_way_in():
    for speed, tcpa in ((NEAR_SPEED, NEAR_TCPA), (FAR_SPEED, FAR_TCPA)):
        scene = crossing(speed)
        context = encounter(scene)
        assert context.situation_type is COLREGSType.CROSSING_FROM_PORT
        assert context.is_give_way_actor(OWN_SHIP) and not context.is_give_way_actor(TARGET)
        assert math.isclose(scene.get_tcpa(TARGET, OWN_SHIP), tcpa, rel_tol=1e-6)
    assert FAR_TCPA > constants().SAFE_TEMPORAL_DISTANCE > NEAR_TCPA


def test_a_near_encounter_has_a_domain_around_its_closest_approach():
    context = encounter(crossing(NEAR_SPEED))
    first, last = violation_times(context)
    assert 0 < first < NEAR_TCPA < last
    assert not context.start_potential_collision_domains[OWN_SHIP].empty
    assert not context.start_potential_collision_domains[TARGET].empty


def test_an_encounter_beyond_the_safe_temporal_distance_still_has_a_domain():
    context = encounter(crossing(FAR_SPEED))
    first, last = violation_times(context)
    assert constants().SAFE_TEMPORAL_DISTANCE < first < FAR_TCPA < last
    assert not context.start_potential_collision_domains[OWN_SHIP].empty
    assert not context.start_potential_collision_domains[TARGET].empty


def test_the_give_way_vessel_of_a_far_encounter_has_a_corridor():
    context = encounter(crossing(FAR_SPEED))
    assert ManeuveringDomain.for_give_way_ship(OWN_SHIP, [context]) is not None
    assert ManeuveringDomain.for_give_way_ship(TARGET, [context]) is None, "the stand-on vessel gets none"


def test_a_pair_in_no_encounter_looks_no_further_than_the_safe_temporal_distance():
    near = OtherSituationContext(OWN_SHIP, TARGET, crossing(NEAR_SPEED), 0, constants())
    far = OtherSituationContext(OWN_SHIP, TARGET, crossing(FAR_SPEED), 0, constants())
    assert len(violation_times(near)) == 2
    assert violation_times(far) == []
    assert far.start_potential_collision_domains[OWN_SHIP].empty


def test_courses_that_never_enter_the_domains_give_no_domain():
    # The target starts 1 km further east and passes 707 m off.
    context = CrossingFromPortSituationContext(OWN_SHIP, TARGET, crossing(NEAR_SPEED, target_x=5000.0), 0, constants())
    assert violation_times(context) == []
    assert context.start_potential_collision_domains[OWN_SHIP].empty
    assert context.start_potential_collision_domains[TARGET].empty
