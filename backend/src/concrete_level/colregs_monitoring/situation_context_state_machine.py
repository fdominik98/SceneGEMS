from typing import Dict, List, Optional, Tuple

from concrete_level.colregs_monitoring.situation_context import (
    COLREGSType,
    CrossingFromPortSituationContext,
    HeadOnSituationContext,
    OtherSituationContext,
    OvertakingSituationContext,
    SituationContext,
    TwoWayCrossingFromPortSituationContext,
    TwoWayCrossingFromStarboardSituationContext,
)
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from utils.colregs_approximations import COLREGSConstraints


class StepSamples:
    """Instants inside one monitor step, on the courses held when the step began.

    Used to decide whether an encounter STARTED during the step. Each vessel is carried
    forward on the course and speed it was steering at the start of the step, rather than
    interpolated toward the scene the step actually ends in, and that difference is the
    whole point of the class. Risk of collision is assessed on the courses vessels are
    observed to be steering, and Rule 8(b) says an alteration made to avoid collision has
    to be large enough to be readily apparent. Interpolating toward the next scene lets a
    vessel escape an encounter with an alteration far below that: measured on a real
    scene, a 2 degree nudge on the first step moved dcpa from 68 m to 264 m against a
    120 m safety distance at 3.7 km range, the pair never counted as an encounter, and
    the overtaking vessel was never asked to give way at all.

    Every relation in a step shares these scenes, and building a ConcreteScene is not
    free (it sets up the logical variables, assignments and evaluation cache), so they
    are built once and only when some relation actually has to look inside the step. A
    step of a second or two has no interior.
    """

    # Four is enough to catch an encounter onset at a 15 s planning step without making
    # the classification, which runs per relation per node, noticeably more expensive.
    SAMPLES_PER_STEP: int = 4

    def __init__(self, current_scene: ConcreteScene, current_timestamp: int, next_scene: ConcreteScene, next_timestamp: int):
        self.current_scene = current_scene
        self.current_timestamp = current_timestamp
        self.next_scene = next_scene
        self.next_timestamp = next_timestamp
        self._samples: Optional[List[Tuple[int, ConcreteScene]]] = None

    @property
    def samples(self) -> List[Tuple[int, ConcreteScene]]:
        if self._samples is None:
            self._samples = self._build()
        return self._samples

    def _build(self) -> List[Tuple[int, ConcreteScene]]:
        step = self.next_timestamp - self.current_timestamp
        if step <= 1:
            return []
        built: List[Tuple[int, ConcreteScene]] = []
        for i in range(1, self.SAMPLES_PER_STEP + 1):
            elapsed = int(round(step * i / (self.SAMPLES_PER_STEP + 1)))
            timestamp = self.current_timestamp + elapsed
            if timestamp <= self.current_timestamp or timestamp >= self.next_timestamp:
                continue
            built.append((timestamp, self._project(elapsed)))
        return built

    def _project(self, elapsed: int) -> ConcreteScene:
        """The scene ``elapsed`` seconds on, with every vessel holding its present course."""
        states: Dict[ConcreteActor, ActorState] = {}
        for actor, current_state in self.current_scene.items():
            states[actor] = actor.simulate(current_state, (current_state.heading, current_state.speed), elapsed)
        return ConcreteScene(states)


class SituationContextStateMachine:
    """Static class for monitoring a single vessel-pair situation context."""

    @staticmethod
    def create_initial(
        scene: ConcreteScene,
        actor1: ConcreteActor,
        actor2: ConcreteActor,
        start_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ) -> SituationContext:
        """Create the initial situation context for a vessel pair.

        The initial scene also accepts a pair at the visibility boundary: the scene
        generator places encounters exactly there (At*CR), the moment the vessels come
        into sight, while stepping only recognises a pair strictly inside visibility.
        """
        return SituationContextStateMachine.get_situation_context(scene, actor1, actor2, start_timestamp, colregs_constants, include_visibility_band=True)

    @staticmethod
    def step(
        current_situation_context: SituationContext,
        step_samples: StepSamples,
        next_scene: ConcreteScene,
        next_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ) -> SituationContext:
        """Calculate the next situation context without mutating the current one."""
        if current_situation_context.get_actors_passed_each_other(next_scene):
            return OtherSituationContext(current_situation_context.actor1, current_situation_context.actor2, next_scene, next_timestamp, colregs_constants)
        candidate = SituationContextStateMachine.get_situation_context(
            next_scene,
            current_situation_context.actor1,
            current_situation_context.actor2,
            next_timestamp,
            colregs_constants,
        )
        if current_situation_context.situation_type == COLREGSType.OTHER and candidate.situation_type == COLREGSType.OTHER:
            # Look inside the step before concluding that nothing happened. An encounter
            # begins the moment the pair comes into visibility on a collision course, and
            # at a 15 s planning step that moment routinely falls between two scenes: the
            # pair can enter and leave the classification entirely within one step, so
            # the planner sees no encounter and assigns no give-way role, while the 1 s
            # replay in the console catches the onset, latches it, and then fails Rule 16
            # against a vessel that was never told it had to act. This is the same
            # end-point sampling hole that SafeDistanceCondition avoids by taking the
            # minimum clearance over the whole step.
            onset = SituationContextStateMachine._find_onset_within_step(current_situation_context, step_samples, colregs_constants)
            if onset is not None:
                return onset
        if current_situation_context.situation_type == COLREGSType.OTHER and candidate.situation_type != COLREGSType.OTHER:
            return candidate
        # An established encounter keeps its roles (they must not flip mid-manoeuvre),
        # but the geometry can still develop into a situation that takes precedence:
        # Rule 13 overrides 14 and 15, so an encounter that becomes an overtaking is
        # relabelled. Without this a latched type could never be corrected.
        if SituationContextStateMachine._takes_precedence(candidate.situation_type, current_situation_context.situation_type):
            return candidate
        return current_situation_context

    @staticmethod
    def _find_onset_within_step(
        current_situation_context: SituationContext,
        step_samples: StepSamples,
        colregs_constants: COLREGSConstraints,
    ) -> Optional[SituationContext]:
        """The earliest non-OTHER classification strictly inside the step, if any.

        The instants come from StepSamples, so they are the pair carried forward on the
        courses it was steering when the step began. The context is anchored at the
        sampled instant, so its start timestamp and start scene are those of the onset
        and time_spent_in_current_context is measured from there.
        """
        actor1 = current_situation_context.actor1
        actor2 = current_situation_context.actor2
        for timestamp, scene in step_samples.samples:
            candidate = SituationContextStateMachine.get_situation_context(scene, actor1, actor2, timestamp, colregs_constants)
            if candidate.situation_type is not COLREGSType.OTHER:
                return candidate
        return None

    # Lower index wins. Rule 13 (overtaking) overrides Rules 14 and 15.
    _PRECEDENCE: List[COLREGSType] = [
        COLREGSType.OVERTAKING_TO_PORT,
        COLREGSType.OVERTAKING_TO_STARBOARD,
        COLREGSType.HEAD_ON,
        COLREGSType.CROSSING_FROM_PORT,
        COLREGSType.TWO_WAY_CROSSING_FROM_PORT,
        COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD,
        COLREGSType.OTHER,
    ]

    @staticmethod
    def _takes_precedence(candidate_type: COLREGSType, current_type: COLREGSType) -> bool:
        precedence = SituationContextStateMachine._PRECEDENCE
        return precedence.index(candidate_type) < precedence.index(current_type)

    @staticmethod
    def get_situation_context(
        scene: ConcreteScene,
        vessel1: ConcreteActor,
        vessel2: ConcreteActor,
        start_timestamp: int,
        colregs_constants: COLREGSConstraints,
        include_visibility_band: bool = False,
    ) -> SituationContext:
        band = include_visibility_band
        if isinstance(vessel1, ConcreteVessel) and isinstance(vessel2, ConcreteVessel):
            if scene.out_of_visibility_distance(vessel1, vessel2):
                return OtherSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            # Rule 13 takes precedence over Rules 14 and 15, so overtaking is tested
            # before head-on and crossing, in both actor orders.
            if scene.in_overtaking_cr(vessel1, vessel2, colregs_constants, band):
                return OvertakingSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_overtaking_cr(vessel2, vessel1, colregs_constants, band):
                return OvertakingSituationContext(vessel2, vessel1, scene, start_timestamp, colregs_constants)
            elif scene.in_head_on_cr(vessel1, vessel2, colregs_constants, band):
                return HeadOnSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_crossing_from_port_cr(vessel1, vessel2, colregs_constants, band):
                return CrossingFromPortSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_crossing_from_port_cr(vessel2, vessel1, colregs_constants, band):
                return CrossingFromPortSituationContext(vessel2, vessel1, scene, start_timestamp, colregs_constants)
            elif scene.in_two_way_crossing_from_port_cr(vessel1, vessel2, colregs_constants, band):
                return TwoWayCrossingFromPortSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
            elif scene.in_two_way_crossing_from_starboard_cr(vessel1, vessel2, colregs_constants, band):
                return TwoWayCrossingFromStarboardSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
        return OtherSituationContext(vessel1, vessel2, scene, start_timestamp, colregs_constants)
