from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON, MAX_DISTANCE
from utils.math_utils import Direction, calculate_heading, relative_heading_direction
from utils.safety_domains import DomainCollection, SafetyDomain


class COLREGSType(Enum):
    OVERTAKING_TO_PORT = auto()  # v1 is in the stern sector of v2; v2 is in the port side sector of v1
    OVERTAKING_TO_STARBOARD = auto()  # v1 is in the stern sector of v2; v2 is in the starboard side sector of v1
    CROSSING_FROM_PORT = auto()  # v1 is in the port side sector of v2; v2 is in the starboard side sector of v1
    HEAD_ON = auto()  # v1 is in the head-on sector of v2; v2 is in the head-on sector of v1
    TWO_WAY_CROSSING_FROM_PORT = auto()  # v1 is in the port side sector of v2; v2 is in the port side sector of v1
    TWO_WAY_CROSSING_FROM_STARBOARD = auto()  # v1 is in the starboard side sector of v2; v2 is in the starboard side sector of v1
    OTHER = auto()  # other situation

    @property
    def custom_name(self) -> str:
        custom_names = {
            COLREGSType.OVERTAKING_TO_PORT: "Overtaking to Port",
            COLREGSType.OVERTAKING_TO_STARBOARD: "Overtaking to Starboard",
            COLREGSType.CROSSING_FROM_PORT: "Crossing from Port",
            COLREGSType.HEAD_ON: "Head-On",
            COLREGSType.TWO_WAY_CROSSING_FROM_PORT: "Two Way Crossing from Port",
            COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD: "Two Way Crossing from Starboard",
            COLREGSType.OTHER: "Other",
        }
        return custom_names[self]


class SituationContext(ABC):
    def __init__(
        self,
        situation_type: COLREGSType,
        actor1: ConcreteActor,
        actor2: ConcreteActor,
        start_scene: ConcreteScene,
        start_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ):
        self.colregs_constants = colregs_constants
        self.situation_type = situation_type
        self.actor1 = actor1
        self.actor2 = actor2
        self.relation = Relation.canonical(actor1, actor2)
        self.start_scene = start_scene
        self.start_timestamp = start_timestamp
        self.actors_on_collision_course = self.get_actors_on_collision_course(start_scene)
        self.actors_have_low_tcpa = self.get_actors_have_low_tcpa(start_scene)
        self.actors_see_each_other = self.get_actors_see_each_other(start_scene)
        self.actors_passed_each_other = self.get_actors_passed_each_other(start_scene)
        self.actors_violate_safety_domain = self.get_actors_violate_safety_domain(start_scene)
        self.actors_right_of_start_state = self.get_actors_right_of_start_state(start_scene)
        self.actors_left_of_start_state = self.get_actors_left_of_start_state(start_scene)
        # Built on first use: a candidate context is constructed for every relation at
        # every steering step and most are discarded, so predicting the encounter for
        # one that never survives is wasted work.
        self._start_potential_collision_domains: Optional[Dict[ConcreteActor, DomainCollection]] = None

    def __str__(self):
        return f"{self.situation_type} - {self.actor1} - {self.actor2}"

    def __repr__(self):
        return str(self)

    @abstractmethod
    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        """The pair's domains for THIS encounter, at the two poses given.

        Taking states rather than a scene is what lets the encounter be predicted: the
        potential collision domain has to evaluate the pair at instants that no scene
        exists for, and building a ConcreteScene per instant is not free (it sets up the
        logical variables, assignments and evaluation cache).
        """

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return self.safety_domains_for_states(scene[self.actor1], scene[self.actor2])

    def get_actors_violate_safety_domain(self, scene: ConcreteScene) -> bool:
        os_safety_domain, ts_safety_domain = self.get_safety_domains(scene)
        return os_safety_domain.contains_point(scene[self.actor2].p) or ts_safety_domain.contains_point(scene[self.actor1].p)

    def other_actor(self, actor: ConcreteActor) -> ConcreteActor:
        return self.actor2 if actor == self.actor1 else self.actor1

    def get_actor_clearance(self, scene: ConcreteScene, actor: ConcreteActor) -> float:
        """Signed clearance of ``actor`` from a safety domain violation in this encounter.

        Negative means the pair violates a domain, zero means they are exactly on the
        boundary, positive is the margin still available. This is the continuous-valued
        counterpart of ``get_actors_violate_safety_domain``: the sign of the two agree,
        so the cost can attract the path toward the boundary while the rule keeps it out.
        Both directions are considered, since either vessel entering the other's domain
        is a violation.
        """
        domain1, domain2 = self.get_safety_domains(scene)
        actor_domain, other_domain = (domain1, domain2) if actor == self.actor1 else (domain2, domain1)
        other = self.other_actor(actor)
        return min(
            other_domain.signed_clearance(scene[actor].p),
            actor_domain.signed_clearance(scene[other].p),
        )

    def get_actor_min_step_clearance(self, current_scene: ConcreteScene, next_scene: ConcreteScene) -> float:
        """Smallest clearance reached anywhere inside the step, not just at its ends.

        Evaluated in the other vessel's frame, where its domain is static and the own
        ship traces a relative segment. Sampling only the endpoints lets a fast relative
        motion pass clean through the domain between two scenes.
        """
        next_domain1, next_domain2 = self.get_safety_domains(next_scene)
        worst = MAX_DISTANCE
        for actor, other_domain in ((self.actor1, next_domain2), (self.actor2, next_domain1)):
            other = self.other_actor(actor)
            # Relative displacement of `actor` with respect to `other`, anchored on the
            # domain pose at the end of the step.
            relative_start = other_domain.center + (current_scene[actor].p - current_scene[other].p)
            relative_end = other_domain.center + (next_scene[actor].p - next_scene[other].p)
            worst = min(worst, other_domain.min_signed_clearance_over_segment(relative_start, relative_end))
        return worst

    def get_actor_side_offset(self, scene: ConcreteScene, actor: ConcreteActor) -> float:
        """Signed lateral deviation of ``actor`` from its own start course, positive when
        it has moved toward the avoidance side this encounter asks for.

        This is the signed form of ``actors_right_of_start_state`` /
        ``actors_left_of_start_state``, so a cost built on it agrees with what
        ``GiveWayEarlyActionCondition.in_maneuver_condition`` accepts.
        """
        direction = self.avoidance_direction(actor)
        start_state = self.start_scene[actor]
        if direction == Direction.RIGHT:
            normal = start_state.v_norm_perp_right
        elif direction == Direction.LEFT:
            normal = start_state.v_norm_perp_left
        else:
            return 0.0
        return float(np.dot(scene[actor].p - start_state.p, normal))

    # How far apart, as a multiple of the pair's safety distance, counts as clear of each
    # other once the closest point of approach is behind them.
    CLEAR_RANGE_FACTOR: float = 2.0

    def get_actors_passed_each_other(self, current_scene: ConcreteScene) -> bool:
        """Finally past and clear.

        Nothing is over until the closest point of approach is behind the pair, which is
        what the tcpa term says. Past that, either the encounter's own geometry has played
        out, or the vessels have simply drawn well apart. The second case is not a
        formality: the per-type conditions describe an encounter that COMPLETES, and an
        overtaking in particular is only complete when the overtaking vessel draws ahead
        of the one it is passing. A give-way vessel that alters away from that vessel
        diverges instead of drawing ahead, so the encounter never completed and never
        ended: measured on a real scene, the pairs were 21 km apart and 2300 s past their
        closest approach with the encounter still live, which pinned the give-way vessel
        to its avoidance course for the whole plan and left it no moment at which to
        resume its original course.
        """
        if current_scene.get_tcpa(self.actor2, self.actor1) >= 0:
            return False
        if self._get_actors_passed_each_other_condition(current_scene):
            return True
        geo_props = current_scene.get_geo_props(self.actor1, self.actor2)
        return geo_props.o_distance > self.CLEAR_RANGE_FACTOR * geo_props.safety_dist

    @abstractmethod
    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        pass

    def get_actors_see_each_other(self, scene: ConcreteScene) -> bool:
        return not scene.out_of_visibility_distance(self.actor2, self.actor1)

    def get_actors_on_collision_course(self, scene: ConcreteScene) -> bool:
        return scene.on_collision_course(self.actor2, self.actor1)

    def get_actors_have_low_tcpa(self, scene: ConcreteScene) -> bool:
        return scene.low_tcpa(self.actor2, self.actor1, self.colregs_constants)

    @abstractmethod
    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        pass

    @abstractmethod
    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        pass

    @abstractmethod
    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        pass

    @property
    def actors(self) -> List[ConcreteActor]:
        return [self.actor1, self.actor2]

    # How finely the predicted violation window is sampled. The window itself is sized
    # by the domains and the closing speed, so a fixed count gives a resolution that
    # scales with the domain rather than with the clock.
    VIOLATION_SAMPLES: int = 64

    @property
    def start_potential_collision_domains(self) -> Dict[ConcreteActor, DomainCollection]:
        """Where each actor's own course runs through this encounter's collision domain.

        Predicted once, from the scene the encounter STARTED in, and then frozen: the
        rules built on it (go around the domain, hold the avoidance course) are about
        the conflict the vessels were obliged to resolve, and recomputing it as they
        manoeuvre would dissolve the obligation the moment the first turn was made.
        """
        if self._start_potential_collision_domains is None:
            domain1, domain2 = self.get_potential_collision_domains(self.start_scene)
            self._start_potential_collision_domains = {self.actor1: domain1, self.actor2: domain2}
        return self._start_potential_collision_domains

    def get_potential_collision_domains(self, scene: ConcreteScene) -> Tuple[DomainCollection, DomainCollection]:
        """The stretch of each actor's present course on which THIS encounter's domains
        would be violated, if neither vessel altered anything.

        Judged against the pair's own COLREGS domains rather than against their static
        ship domains. The static circle is a property of the hull, not of the encounter:
        it is the same disc whether the vessels are meeting head-on, crossing or
        overtaking, while the room a give-way vessel actually has to leave differs in
        every one of those (an elongated bow domain head-on, a domain shifted toward the
        phantom ship when crossing). Estimating the manoeuvre against the circle
        therefore asks for a deviation that has nothing to do with the encounter being
        resolved, and the alteration it produces is either short or gratuitous.

        Each collection stands on its OWN actor's track, because that is the question
        ``has_passed`` and ``in_front_of`` ask, and it carries the extent of both
        domains: the conflict is over only when neither containment can happen.
        """
        state1, state2 = scene[self.actor1], scene[self.actor2]
        # Each collection is read against its own actor's course, so that is the frame
        # its bounding rectangle is measured in.
        collection1, collection2 = DomainCollection(state1.heading), DomainCollection(state2.heading)
        for time in self.domain_violation_times(state1, state2):
            predicted1, predicted2 = self._predicted_states(state1, state2, time)
            domain1, domain2 = self.safety_domains_for_states(predicted1, predicted2)
            collection1.add_safety_domain(domain1)
            collection1.add_safety_domain(self._re_anchored(domain2, predicted1.p))
            collection2.add_safety_domain(domain2)
            collection2.add_safety_domain(self._re_anchored(domain1, predicted2.p))
        return collection1, collection2

    def domain_violation_times(self, state1: ActorState, state2: ActorState) -> List[float]:
        """When the pair would enter and leave a violation of this encounter's domains.

        The domains are not all circles, so there is no closed form. A closed-form solve
        against the domains' bounding circles gives a window that certainly contains any
        violation, and the true instants are picked out of it by sampling. An empty
        result means the courses they are steering do not bring them into conflict at
        all, which is a legitimate answer and not a failure to find one.
        """
        window = self._bounding_violation_window(state1, state2)
        if window is None:
            return []
        lower, upper = window
        violating: List[float] = []
        for sample in range(self.VIOLATION_SAMPLES + 1):
            time = lower + (upper - lower) * sample / self.VIOLATION_SAMPLES
            predicted1, predicted2 = self._predicted_states(state1, state2, time)
            domain1, domain2 = self.safety_domains_for_states(predicted1, predicted2)
            if domain1.contains_point(predicted2.p) or domain2.contains_point(predicted1.p):
                violating.append(time)
        if len(violating) < 2:
            return violating
        return [violating[0], violating[-1]]

    def _bounding_violation_window(self, state1: ActorState, state2: ActorState) -> Optional[Tuple[float, float]]:
        """Times within which a violation is possible at all, from the bounding circles.

        Bounded ahead by the safe temporal distance: a conflict further off than that is
        not one the vessels have to resolve now, and it is the same horizon the risk of
        collision itself is judged over.
        """
        domain1, domain2 = self.safety_domains_for_states(state1, state2)
        reach = max(self._domain_reach(domain1, state1), self._domain_reach(domain2, state2))
        horizon = float(self.colregs_constants.SAFE_TEMPORAL_DISTANCE)

        relative_position = state2.p - state1.p
        relative_velocity = state2.v - state1.v
        closing_speed_squared = float(np.dot(relative_velocity, relative_velocity))
        if closing_speed_squared <= EPSILON:
            # Same velocity: the separation never changes, so it is either a violation
            # for the whole horizon or for none of it.
            return (0.0, horizon) if float(np.dot(relative_position, relative_position)) <= reach**2 else None

        b = 2.0 * float(np.dot(relative_position, relative_velocity))
        c = float(np.dot(relative_position, relative_position)) - reach**2
        discriminant = b**2 - 4.0 * closing_speed_squared * c
        if discriminant < 0:
            return None

        root = float(np.sqrt(discriminant))
        lower = max((-b - root) / (2.0 * closing_speed_squared), 0.0)
        upper = min((-b + root) / (2.0 * closing_speed_squared), horizon)
        if upper < lower:
            return None
        return lower, upper

    def _predicted_states(self, state1: ActorState, state2: ActorState, time: float) -> Tuple[ActorState, ActorState]:
        """Both actors carried forward ``time`` seconds on the courses they are steering."""
        return (
            self.actor1.simulate(state1, (state1.heading, state1.speed), time),
            self.actor2.simulate(state2, (state2.heading, state2.speed), time),
        )

    @staticmethod
    def _re_anchored(domain: SafetyDomain, position: np.ndarray) -> SafetyDomain:
        """A copy of ``domain``, shape and orientation intact, moved onto ``position``.

        Each collection stands on its own actor's track, so the other vessel's domain has
        to be carried across to that track to say how much room the pair needs there.
        Substituting its bounding circle instead would give an elongated domain the beam
        of its own length, and the vessel would be sent half as far around again as the
        encounter asks for: measured on a 50 m head-on pair, 487 m of lateral extent
        against the 200 m the domain actually has.
        """
        offset = position - domain.center
        return domain.shift(float(np.linalg.norm(offset)), calculate_heading(offset))

    @staticmethod
    def _domain_reach(domain: SafetyDomain, state: ActorState) -> float:
        """How far a domain can extend from the pose it belongs to.

        The COLREGS domains are shifted off the vessel (toward the bow head-on, toward
        the phantom ship when crossing), so the distance from the vessel is the offset
        plus the domain's own radius, not the radius alone.
        """
        return float(np.linalg.norm(domain.center - state.p)) + domain.bounding_circle.radius

    def get_actors_passed_potential_collision_domain(self, scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: self.start_potential_collision_domains[self.actor1].has_passed(scene[self.actor1]),
            self.actor2: self.start_potential_collision_domains[self.actor2].has_passed(scene[self.actor2]),
        }

    def get_actors_in_front_of_potential_collision_domain(self, scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: self.start_potential_collision_domains[self.actor1].in_front_of(scene[self.actor1]),
            self.actor2: self.start_potential_collision_domains[self.actor2].in_front_of(scene[self.actor2]),
        }

    def get_actors_right_of_start_state(self, next_scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: next_scene[self.actor1].right_of(self.start_scene[self.actor1]),
            self.actor2: next_scene[self.actor2].right_of(self.start_scene[self.actor2]),
        }

    def get_actors_left_of_start_state(self, next_scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: next_scene[self.actor1].left_of(self.start_scene[self.actor1]),
            self.actor2: next_scene[self.actor2].left_of(self.start_scene[self.actor2]),
        }


class HeadOnSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.HEAD_ON, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.RIGHT

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_head_on_safety_domain(state1),
            self.actor2.get_head_on_safety_domain(state2),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False


class OvertakingSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        # The caller has already established visibility and collision risk (strictly
        # inside visibility, or at its boundary for an initial scene), so only the
        # bearing geometry decides the side here.
        if start_scene.overtaking_to_port(vessel1, vessel2, colregs_constants):
            situation_type = COLREGSType.OVERTAKING_TO_PORT
        elif start_scene.overtaking_to_starboard(vessel1, vessel2, colregs_constants):
            situation_type = COLREGSType.OVERTAKING_TO_STARBOARD
        else:
            raise ValueError(f"Invalid overtaking situation: {start_scene.in_overtaking_cr(vessel1, vessel2, colregs_constants, include_visibility_band=True)}")
        super().__init__(situation_type, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

        # if actor2 is facing right of the collision domain of actor1 then left else right.
        # With no predicted collision domain the collection is empty and its bounding
        # rectangle reports heading 0.0 (due east), which would decide the overtaking
        # side against an arbitrary compass direction. Fall back to the overtaken
        # vessel's own heading, which is the reference an overtaking manoeuvre is
        # actually judged against.
        overtaken_reference_heading = (
            self.start_scene[self.actor1].heading if self.start_potential_collision_domains[self.actor1].empty else self.start_potential_collision_domains[self.actor1].heading
        )
        actor2_relative_heading_to_collision_domain = relative_heading_direction(self.start_scene[self.actor2].heading, overtaken_reference_heading)

        self.avoidance_directions = {
            self.actor1: Direction.LEFT if actor2_relative_heading_to_collision_domain == Direction.RIGHT else Direction.RIGHT,
            self.actor2: Direction.FORWARD,
        }

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.avoidance_directions[actor]

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_overtaking_safety_domain(state1),
            self.actor2.get_default_safety_domain(state2),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].in_front_of(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return self.actor2 == actor


class CrossingFromPortSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.CROSSING_FROM_PORT, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

        self.avoidance_directions = {
            self.actor1: Direction.RIGHT,
            self.actor2: Direction.FORWARD,
        }

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.avoidance_directions[actor]

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_port_safety_domain(state1),
            self.actor2.get_default_safety_domain(state2),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].right_of(current_scene[self.actor2]) and current_scene[self.actor1].behind(current_scene[self.actor2])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return self.actor2 == actor


class TwoWayCrossingFromPortSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.TWO_WAY_CROSSING_FROM_PORT, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.RIGHT

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_port_safety_domain(state1),
            self.actor2.get_crossing_from_port_safety_domain(state2),
        )

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])


class TwoWayCrossingFromStarboardSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.LEFT

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_starboard_safety_domain(state1),
            self.actor2.get_crossing_from_starboard_safety_domain(state2),
        )

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])


class OtherSituationContext(SituationContext):
    def __init__(self, actor1: ConcreteActor, actor2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.OTHER, actor1, actor2, start_scene, start_timestamp, colregs_constants)

    def safety_domains_for_states(self, state1: ActorState, state2: ActorState) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_default_safety_domain(state1),
            self.actor2.get_default_safety_domain(state2),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return True

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return False

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        # No encounter means no Rule 17 obligation. Reporting both actors as stand-on
        # made StandOnCoursePersistenceCondition forbid any course change for a vessel
        # that is in no encounter at all, or merely paired with a static obstacle, and
        # prevented a give-way vessel from ever returning toward its original course
        # once the pair had passed and the context reverted to OTHER.
        return False

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return {self.actor1: Direction.FORWARD, self.actor2: Direction.FORWARD}[actor]


@dataclass(frozen=False)
class SituationContextSet(Dict[Relation, SituationContext]):
    def __init__(self, situation_contexts: Dict[Relation, SituationContext], actors_have_to_give_way: Dict[ConcreteActor, bool], actors_avoidance_directions: Dict[ConcreteActor, Direction]):
        super().__init__(situation_contexts)
        self.actors_have_to_give_way = actors_have_to_give_way
        self.actors_avoidance_directions = actors_avoidance_directions

    def actor_has_to_give_way(self, actor: ConcreteActor) -> bool:
        return self.actors_have_to_give_way.get(actor, False)

    def actor_avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.actors_avoidance_directions.get(actor, Direction.FORWARD)

    def resolved_avoidance_direction(self, relation: Relation, actor: ConcreteActor) -> Direction:
        """Which side ``actor`` should pass on, for the one encounter ``relation`` names.

        Normally the encounter's own direction, because a give-way rule is about one
        encounter and the collapsed accessor above flattens every relation the actor is
        in down to a single side (preferring RIGHT), which can contradict it.

        The exception is when the encounters genuinely disagree, which happens when an
        actor is give-way in two situations that ask for opposite alterations. Then the
        per-encounter directions are jointly unsatisfiable, and honouring them separately
        is worse than breaking the tie: suggestions are merged by INTERSECTION across
        relations, so opposite sides intersect to nothing, the vessel is left with no
        admissible manoeuvre and every successor is a dead end.

        Callers should not ask this every scene. It is the seed for the value carried on
        COLREGSMonitorState, which is what rules read; see
        ``COLREGSMonitorState.actors_avoidance_direction``.
        """
        if self.actor_has_conflicting_avoidance_directions(actor):
            return self.actor_avoidance_direction(actor)
        return self[relation].avoidance_direction(actor)

    def actor_avoidance_directions(self, actor: ConcreteActor) -> Set[Direction]:
        """The distinct sides this actor is being asked to pass on, across all its encounters.

        FORWARD is dropped: it means "no alteration is called for in that encounter",
        which never contradicts an alteration called for in another one.
        """
        return {situation_context.avoidance_direction(actor) for relation, situation_context in self.items() if actor in relation} - {Direction.FORWARD}

    def actor_has_conflicting_avoidance_directions(self, actor: ConcreteActor) -> bool:
        """True when two encounters ask this actor to alter to opposite sides.

        A vessel give-way in two situations at once can be told to turn to starboard for
        one and to port for the other. There is no course that satisfies both, and the
        rules judge each encounter on its own, so something has to break the tie: that is
        what ``actor_avoidance_direction`` is for. Rules ask this first so they only fall
        back on the collapsed direction when the per-encounter ones genuinely disagree.
        """
        return len(self.actor_avoidance_directions(actor)) > 1

    @property
    def actors(self) -> List[ConcreteActor]:
        return list(set([context.actor1 for context in self.values()] + [context.actor2 for context in self.values()]))

    @property
    def relations(self) -> List[Relation]:
        return list(self.keys())

    @staticmethod
    def get_actor_has_to_give_way(actor: ConcreteActor, situation_context_set: Dict[Relation, SituationContext]) -> bool:
        return any(actor in relation and situation_context.is_give_way_actor(actor) for relation, situation_context in situation_context_set.items())

    @staticmethod
    def get_actor_avoidance_direction(actor: ConcreteActor, situation_context_set: Dict[Relation, SituationContext]) -> Direction:
        avoidance_directions = {situation_context.avoidance_direction(actor) for relation, situation_context in situation_context_set.items() if actor in relation}
        if Direction.RIGHT in avoidance_directions:
            return Direction.RIGHT

        if Direction.LEFT in avoidance_directions:
            return Direction.LEFT

        return Direction.FORWARD
