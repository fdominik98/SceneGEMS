"""SituationContextStateMachine: a pair inside the safety domain of its encounter is always in OTHER, a pair that has been in sight stays in sight, and a running encounter keeps its type."""

import math
from typing import List

from concrete_level.colregs_monitoring.situation_context import COLREGSType, OtherSituationContext, SituationContext
from concrete_level.colregs_monitoring.situation_context_state_machine import SituationContextStateMachine, StepSamples
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants

# Head-on along the x axis: 2000 m is clear of every domain, 200 m is inside the own
# ship's head-on ellipse but outside its default circle, so only the encounter's own
# domain catches it.
CLEAR, INSIDE_HEAD_ON_DOMAIN = 2000.0, 200.0
# Two 30 m vessels meeting are in sight from 5 nm (9260 m): 12 km is beyond that range.
BEYOND_VISIBILITY = 12000.0


def head_on(distance: float) -> ConcreteScene:
    return ConcreteScene({OWN_SHIP: ActorState(0.0, 0.0, SPEED, 0.0), TARGET: ActorState(distance, 0.0, SPEED, math.pi)})


def initial(scene: ConcreteScene) -> SituationContext:
    return SituationContextStateMachine.create_initial(scene, OWN_SHIP, TARGET, 0, constants())


def step(current: SituationContext, current_scene: ConcreteScene, next_scene: ConcreteScene, next_timestamp: int, already_in_sight: bool = False) -> SituationContext:
    samples = StepSamples(current_scene, current.start_timestamp, next_scene, next_timestamp)
    return SituationContextStateMachine.step(current, samples, next_scene, next_timestamp, constants(), already_in_sight)


def test_the_test_geometry_is_inside_the_head_on_domain_but_outside_the_default_circle():
    scene = head_on(INSIDE_HEAD_ON_DOMAIN)
    assert OWN_SHIP.get_head_on_safety_domain(scene[OWN_SHIP]).contains_point(scene[TARGET].p)
    assert not OWN_SHIP.get_default_safety_domain(scene[OWN_SHIP]).contains_point(scene[TARGET].p)


def test_a_head_on_pair_clear_of_its_domain_is_head_on():
    assert initial(head_on(CLEAR)).situation_type is COLREGSType.HEAD_ON


def test_an_initial_pair_inside_its_encounter_domain_is_other():
    assert initial(head_on(INSIDE_HEAD_ON_DOMAIN)).situation_type is COLREGSType.OTHER


def test_a_running_encounter_ends_when_its_domain_is_violated():
    start = head_on(CLEAR)
    current = initial(start)
    assert current.situation_type is COLREGSType.HEAD_ON
    following = head_on(INSIDE_HEAD_ON_DOMAIN)
    after = step(current, start, following, 1)
    assert after.situation_type is COLREGSType.OTHER
    assert after.start_scene is following and after.start_timestamp == 1


def test_an_encounter_does_not_start_while_its_domain_is_violated():
    start = head_on(CLEAR)
    current = OtherSituationContext(OWN_SHIP, TARGET, start, 0, constants())
    assert step(current, start, head_on(INSIDE_HEAD_ON_DOMAIN), 1).situation_type is COLREGSType.OTHER


def test_an_encounter_starts_once_the_pair_is_clear_of_its_domain():
    start = head_on(INSIDE_HEAD_ON_DOMAIN)
    current = initial(start)
    assert current.situation_type is COLREGSType.OTHER
    assert step(current, start, head_on(CLEAR), 1).situation_type is COLREGSType.HEAD_ON


def test_an_onset_inside_the_step_is_other_when_the_step_ends_inside_its_domain():
    # The samples inside a 15 s step see a clear head-on on the held courses, so the
    # onset search finds an encounter, but the scene the step ends in violates it.
    start = head_on(CLEAR)
    current = OtherSituationContext(OWN_SHIP, TARGET, start, 0, constants())
    samples = StepSamples(start, 0, head_on(INSIDE_HEAD_ON_DOMAIN), 15)
    assert SituationContextStateMachine._find_onset_within_step(current, samples, constants()).situation_type is COLREGSType.HEAD_ON
    assert step(current, start, head_on(INSIDE_HEAD_ON_DOMAIN), 15).situation_type is COLREGSType.OTHER


def test_a_collision_course_beyond_visibility_is_no_encounter_for_a_pair_never_in_sight():
    start = head_on(BEYOND_VISIBILITY)
    assert not start.in_sight(OWN_SHIP, TARGET, include_visibility_band=True)
    current = initial(start)
    assert current.situation_type is COLREGSType.OTHER
    assert step(current, start, head_on(BEYOND_VISIBILITY - 2 * SPEED), 1).situation_type is COLREGSType.OTHER


def test_a_pair_that_has_been_in_sight_starts_an_encounter_beyond_visibility():
    start = head_on(BEYOND_VISIBILITY)
    current = initial(start)
    after = step(current, start, head_on(BEYOND_VISIBILITY - 2 * SPEED), 1, already_in_sight=True)
    assert after.situation_type is COLREGSType.HEAD_ON


def test_an_onset_inside_the_step_also_counts_a_pair_that_has_been_in_sight():
    start = head_on(BEYOND_VISIBILITY)
    current = OtherSituationContext(OWN_SHIP, TARGET, start, 0, constants())
    samples = StepSamples(start, 0, head_on(BEYOND_VISIBILITY - 30 * SPEED), 15)
    assert SituationContextStateMachine._find_onset_within_step(current, samples, constants()) is None
    assert SituationContextStateMachine._find_onset_within_step(current, samples, constants(), already_in_sight=True).situation_type is COLREGSType.HEAD_ON


def test_having_been_in_sight_does_not_make_an_encounter_without_a_collision_course():
    # Parallel courses 12 km apart: the tracks never come within the safety distance.
    start = ConcreteScene({OWN_SHIP: ActorState(0.0, 0.0, SPEED, 0.0), TARGET: ActorState(0.0, BEYOND_VISIBILITY, SPEED, 0.0)})
    following = ConcreteScene({OWN_SHIP: ActorState(SPEED, 0.0, SPEED, 0.0), TARGET: ActorState(SPEED, BEYOND_VISIBILITY, SPEED, 0.0)})
    assert step(initial(start), start, following, 1, already_in_sight=True).situation_type is COLREGSType.OTHER


# A crossing in which the bearing drifts into the stern sector: the own ship heads north,
# the faster target comes up from 16 degrees abaft its starboard beam and would pass
# 110 m off, inside the 120 m safety distance. From 255 s the target bears more than
# 22.5 degrees abaft the beam, which on its own is an overtaking by the target. At 360 s
# the pair is inside the domain of the crossing.
DRIFT_OWN_SPEED, DRIFT_TARGET_SPEED, DRIFT_TARGET_HEADING = 4.8, 8.56, 2.3354
DRIFT_TARGET_START = (2110.0, -603.0)
DRIFT_STEP, DRIFT_INTO_STERN_SECTOR, DRIFT_INSIDE_DOMAIN = 15, 255, 360


def drifting_crossing(time: int) -> ConcreteScene:
    target_x = DRIFT_TARGET_START[0] + DRIFT_TARGET_SPEED * math.cos(DRIFT_TARGET_HEADING) * time
    target_y = DRIFT_TARGET_START[1] + DRIFT_TARGET_SPEED * math.sin(DRIFT_TARGET_HEADING) * time
    return ConcreteScene(
        {
            OWN_SHIP: ActorState(0.0, DRIFT_OWN_SPEED * time, DRIFT_OWN_SPEED, math.pi / 2),
            TARGET: ActorState(target_x, target_y, DRIFT_TARGET_SPEED, DRIFT_TARGET_HEADING),
        }
    )


def classified_alone(scene: ConcreteScene) -> SituationContext:
    """What the scene classifies as on its own, with no encounter running."""
    return SituationContextStateMachine.get_situation_context(scene, OWN_SHIP, TARGET, 0, constants(), already_in_sight=True)


def drifting_crossing_contexts(until: int) -> List[SituationContext]:
    """The pair's context at every step of the drifting crossing, from 0 s up to and including ``until``."""
    contexts = [initial(drifting_crossing(0))]
    for time in range(DRIFT_STEP, until + 1, DRIFT_STEP):
        samples = StepSamples(drifting_crossing(time - DRIFT_STEP), time - DRIFT_STEP, drifting_crossing(time), time)
        contexts.append(SituationContextStateMachine.step(contexts[-1], samples, drifting_crossing(time), time, constants(), already_in_sight=True))
    return contexts


def test_the_drifting_crossing_alone_would_classify_as_an_overtaking_by_the_target():
    before = classified_alone(drifting_crossing(DRIFT_INTO_STERN_SECTOR - DRIFT_STEP))
    after = classified_alone(drifting_crossing(DRIFT_INTO_STERN_SECTOR))
    assert before.situation_type is COLREGSType.CROSSING_FROM_PORT and before.is_give_way_actor(OWN_SHIP)
    assert after.situation_type is COLREGSType.OVERTAKING_TO_PORT and after.is_give_way_actor(TARGET)


def test_a_running_crossing_is_not_relabelled_when_the_bearing_drifts_into_the_stern_sector():
    contexts = drifting_crossing_contexts(DRIFT_INSIDE_DOMAIN - DRIFT_STEP)
    start = contexts[0]
    assert start.situation_type is COLREGSType.CROSSING_FROM_PORT
    assert start.is_give_way_actor(OWN_SHIP) and start.is_stand_on_actor(TARGET)
    # The same context object all the way: type, roles, start scene and frozen domains.
    assert all(context is start for context in contexts)


def test_the_running_crossing_ends_only_when_its_domain_is_entered():
    last_scene = drifting_crossing(DRIFT_INSIDE_DOMAIN - DRIFT_STEP)
    assert last_scene.get_tcpa(TARGET, OWN_SHIP) > 0, "the risk of collision is not resolved yet"
    ended = drifting_crossing_contexts(DRIFT_INSIDE_DOMAIN)[-1]
    assert ended.situation_type is COLREGSType.OTHER
    assert ended.start_timestamp == DRIFT_INSIDE_DOMAIN
