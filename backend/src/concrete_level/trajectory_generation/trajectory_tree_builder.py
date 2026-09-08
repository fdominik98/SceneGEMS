import random
from itertools import product
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverStateSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults, MonitoredTrajectory
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from utils.global_constants import EPSILON, MAX_DISTANCE
from utils.interval import Interval
from utils.math_utils import calculate_heading, distance, heading_diff, rotate_heading
from utils.safety_domains import DomainCollection


class SceneNode:
    def __init__(self, monitored_scene_with_results: MonitoredSceneWithResults):
        self.monitored_scene_with_results = monitored_scene_with_results
        self.id = -1
        self.parent: Optional[int] = None
        self.children: Set[int] = set()
        # Set when steering produced no successor at all: the node is a sampling dead
        # end, not a COLREGS failure, so it stays on the tree (it may still be the best
        # path found) but is skipped when picking nodes to expand.
        self.is_dead_end = False
        # Consecutive expansions where every successor was refused by the rejoin filter.
        # That refusal is a property of the sampled heading, not of the node, so one bad
        # round says nothing: the admissible turn may simply not have been drawn. Only a
        # run of them means the node really cannot go anywhere.
        self.rejoin_rejection_streak = 0
        # Per-actor memo of TrajectoryObjective.calculate_bounding_rect. The inputs are
        # all frozen on the node, so the union is computed once instead of on every sort.
        self.potential_collision_domain_cache: Dict[ConcreteActor, DomainCollection] = {}
        # Heading change that produced this node, per actor: the current turn rate.
        # Used to keep the turn rate continuous and to price curvature in the cost.
        self.heading_steps: Dict[ConcreteActor, float] = {}
        # Cumulative cost of the path from the root to this node.
        self.path_cost: float = 0.0
        # Closest this actor has come to a domain violation anywhere on the path so far,
        # and the side offset it held at that moment. The magnet is about the closest
        # point of approach, so it is judged on these running extremes once at the end
        # rather than charged at every node (which would just penalise being far from
        # the encounter early on, and make short paths always win).
        self.min_clearance: Dict[ConcreteActor, float] = {}
        self.side_offset_at_min_clearance: Dict[ConcreteActor, float] = {}
        # Per-actor end point, as a distance along the actor's ORIGINAL course measured
        # from its start state. Inherited from the parent and only ever raised, so a
        # vessel drawn into a second COLREGS situation part way along a branch gets an
        # end point far enough out to resolve that one and rejoin afterwards, while a
        # node stays comparable with its own descendants. Empty means "use the root
        # estimate"; see TrajectoryObjective.goal_distance.
        self.goal_distances: Dict[ConcreteActor, float] = {}
        # Actors that have been in a COLREGS situation anywhere on the path so far.
        # "No live encounter" is true both before the first one latches and after the
        # last one clears, and those two states call for opposite behaviour, so telling
        # them apart needs the path, not the scene. Monotone: once set, never cleared.
        self.encountered: Set[ConcreteActor] = set()

    def inherit_running_extremes(self, parent: "SceneNode") -> None:
        self.min_clearance = dict(parent.min_clearance)
        self.side_offset_at_min_clearance = dict(parent.side_offset_at_min_clearance)
        self.encountered = set(parent.encountered)
        for situation_context, colregs_state in self.monitored_scene_with_results.colregs_states_with_context:
            if situation_context.situation_type is COLREGSType.OTHER:
                continue
            for actor in situation_context.actors:
                self.encountered.add(actor)
                clearance = colregs_state.actors_clearance.get(actor)
                if clearance is None:
                    continue
                if actor not in self.min_clearance or clearance < self.min_clearance[actor]:
                    self.min_clearance[actor] = clearance
                    self.side_offset_at_min_clearance[actor] = colregs_state.actors_side_offset.get(actor, 0.0)

    @property
    def scene(self) -> ConcreteScene:
        return self.monitored_scene_with_results.scene

    @property
    def colregs_state_set(self) -> COLREGSMonitorStateSet:
        return self.monitored_scene_with_results.colregs_state_set

    @property
    def monitor_result_map_set(self) -> COLREGSRuleResultMapSet:
        return self.monitored_scene_with_results.monitor_result_map_set

    @property
    def maneuver_state_set(self) -> ManeuverStateSet:
        return self.monitored_scene_with_results.maneuver_state_set

    @property
    def maneuver_suggestions(self) -> ManeuverSuggestions:
        return self.monitored_scene_with_results.maneuver_suggestions

    def add_child(self, child: "SceneNode"):
        self.children.add(child.id)
        child.parent = self.id

    def remove_child(self, child: "SceneNode"):
        self.children.discard(child.id)
        child.parent = None

    @property
    def is_root(self) -> bool:
        return self.parent is None


class TrajectoryObjective:
    def __init__(self, actor: ConcreteActor, root: SceneNode, time_step: int, verbose: bool = False, goal_horizon: float = 0.0):
        self.actor = actor
        self.relation = Relation(actor, actor)
        self.time_step = time_step
        self.start_state = root.scene[self.actor]
        self.potential_collision_domain = self.calculate_bounding_rect(root)
        self.verbose = verbose

        # The original course as an orthonormal frame. Every distance in this class is
        # expressed in it: "along" is progress down the original track and "across" is
        # the cross-track offset from it.
        self.forward = np.array([np.cos(self.start_state.heading), np.sin(self.start_state.heading)])
        self.across = np.array([-np.sin(self.start_state.heading), np.cos(self.start_state.heading)])

        # Turn magnitude the rejoin is planned at. A correction has to be readily
        # apparent to be admissible at all (see maneuver._detectable_heading_step), so
        # this is the angle the return leg will actually be flown at.
        self.rejoin_alteration = root.maneuver_state_set[self.relation].colregs_constants.READILY_APPARENT_HEADING_CHANGE

        # Distance the vessel would cover on its original course over the planning
        # horizon. The end point is capped by it: the planner cannot plan past the
        # horizon, so a goal beyond it is not a goal, it is just a direction. It is also
        # capped by MAX_DISTANCE. A goal 34 km away makes the distance-to-goal term
        # effectively constant over the whole search, which leaves the cost with no
        # gradient and lets the vessel wander in circles at no charge.
        self.horizon_distance = self.actor.distance_made(self.start_state, (self.start_state.heading, self.start_state.speed), max(goal_horizon, time_step))
        # Along-track distance at which the encounters known at the root are behind the
        # vessel. Kept so the goal test can ask whether the encounter has been run past,
        # which is a different question from whether the end point has been reached.
        self.start_resolve_distance = self.resolve_distance(root)
        self.start_goal_distance = self.estimate_goal_distance(root)
        self.goal_position = self.actor.simulate_distance(self.start_state, self.start_goal_distance).p

    # How many steps of straight running to leave between the rejoin and the end point,
    # so the path finishes settled on the original course instead of still turning.
    SETTLE_STEPS: int = 3
    # How close to the original track counts as rejoined, in safety radii. The manoeuvre
    # bands are quantised (plus or minus 2 deg, or a readily apparent turn), so the track
    # cannot be recaptured exactly and a tolerance is not optional here.
    REJOIN_TOLERANCE_FRACTION: float = 1.0

    def along_track(self, state: ActorState) -> float:
        """Progress down the original track, in metres from the start state."""
        return float(np.dot(state.p - self.start_state.p, self.forward))

    def cross_track(self, state: ActorState) -> float:
        """Signed offset from the original track, positive to port of it."""
        return float(np.dot(state.p - self.start_state.p, self.across))

    def resolve_distance(self, node: SceneNode) -> float:
        """Along-track distance from ``node`` to where its encounters are behind it.

        Taken from the potential collision domains of the COLREGS situations this actor
        is give-way in: the far edge of their union, projected onto the original course.
        With no such situation there is nothing to run past and the distance is zero.

        It used to fall back, when no domain existed, to the constant-course closest
        approach against EVERY other vessel plus the time to open by their combined
        static safety radii. That is the wrong quantity twice over. It counts vessels
        the actor is in no encounter with, and it measures the encounter with the hull's
        static circle instead of with the domain the encounter is actually judged
        against. At the root, where every pair is still classified OTHER, it is also the
        only estimate there is, so it set the whole plan: on a scene whose nearest
        closest approach was 900 s away it put the end point 9.2 km up a track the
        planner could only cover 3.8 km of, which left the goal term with no gradient
        and made the "back on track and steady" half of ``reached_goal`` unreachable.
        """
        state = node.scene[self.actor]
        domains = self.calculate_bounding_rect(node)
        if domains.empty:
            return 0.0
        return max(float(np.dot(domains.bounding_rectangle.front_point - state.p, self.forward)), 0.0)

    def estimate_goal_distance(self, node: SceneNode) -> float:
        """Where this actor should be back on its original track, as an along-track distance.

        Three legs, all measured along the original course so they compose additively:

        - ``resolve``: how much further it has to run before the encounter is behind it.
        - ``rejoin``: the return leg. Holding an alteration of theta for the resolve leg
          puts the vessel ``v * T * sin(theta)`` off track, and closing that at the same
          theta costs ``v * T * cos(theta)`` of along-track distance, so the return leg
          is the resolve leg scaled by cos(theta). Any offset the vessel has ALREADY
          built up costs ``offset / tan(theta)`` on top, which is zero at the root.
        - ``settle``: a few steps of straight running so the path ends on the track and
          not still turning.

        Capped at the horizon: if the estimate does not fit, there is no room for a full
        rejoin and the vessel gets as far back as the horizon allows.
        """
        state = node.scene[self.actor]
        resolve = self.resolve_distance(node)
        alteration = max(self.rejoin_alteration, EPSILON)
        rejoin = resolve * float(np.cos(alteration)) + abs(self.cross_track(state)) / max(float(np.tan(alteration)), EPSILON)
        settle = self.SETTLE_STEPS * state.speed * self.time_step
        goal_distance = self.along_track(state) + resolve + rejoin + settle
        return float(min(max(goal_distance, settle), self.horizon_distance, MAX_DISTANCE))

    def goal_distance(self, node: SceneNode) -> float:
        return node.goal_distances.get(self.actor, self.start_goal_distance)

    def goal_position_at(self, node: SceneNode) -> np.ndarray:
        """The end point for this actor on the branch that ends at ``node``."""
        return self.start_state.p + self.forward * self.goal_distance(node)

    def aim_point(self, node: SceneNode) -> np.ndarray:
        """Where goal-biased sampling should point this actor.

        Aiming at the end point does not work once the vessel is off track and the
        encounter is behind it. The end point sits far down the original course, so from
        2 km off with 9 km still to run the bearing to it is about 12 deg, and the
        admissible bands at dt=15 are the persisting band (2 deg) and a readily apparent
        course change (15.3 deg and up). A 12 deg bearing falls in the gap between them,
        so the biased sample can only ever offer a 2 deg nudge and the vessel drifts back
        onto its original HEADING while staying kilometres off its original TRACK.

        A track intercept one capture length ahead gives a bearing at the alteration
        angle itself, which lands inside the readily apparent band, so the turn back is
        actually proposed. This is pure pursuit onto the track.
        """
        state = node.scene[self.actor]
        offset = self.cross_track(state)
        tolerance = self.REJOIN_TOLERANCE_FRACTION * max(self.actor.safety_radius, EPSILON)
        if not self.is_past_encounter(node) or abs(offset) <= tolerance:
            return self.goal_position_at(node)
        capture_length = abs(offset) / max(float(np.tan(max(self.rejoin_alteration, EPSILON))), EPSILON)
        intercept_along = min(self.along_track(state) + capture_length, self.goal_distance(node))
        return self.start_state.p + self.forward * intercept_along

    def updated_goal_distance(self, parent: SceneNode, node: SceneNode) -> float:
        """The end point carried from ``parent``, raised if ``node`` needs a further one.

        Only ever raised. Recomputing freely would let the end point drift with every
        step and reproduce the receding goal this replaced; taking the maximum means it
        moves exactly when a new COLREGS situation makes the old estimate too short, and
        stays put otherwise.
        """
        inherited = self.goal_distance(parent)
        if self.is_past_encounter(node):
            return inherited
        return max(inherited, self.estimate_goal_distance(node))

    def calculate_bounding_rect(self, node: SceneNode) -> DomainCollection:
        cached = node.potential_collision_domain_cache.get(self.actor)
        if cached is not None:
            return cached
        domains = DomainCollection()
        for situation_context, colregs_state in node.monitored_scene_with_results.colregs_states_with_context:
            if not situation_context.is_give_way_actor(self.actor):
                continue
            # Only this actor's own progress past its domain matters; `any(...)` also
            # dropped the domain whenever the OTHER actor was past its one.
            if colregs_state.actors_in_front_of_potential_collision_domain.get(self.actor, False):
                continue
            domains = domains.union(situation_context.start_potential_collision_domains[self.actor])
        node.potential_collision_domain_cache[self.actor] = domains
        return domains

    # Cost weights. Every term below is dimensionless, so these are directly comparable.
    # The old cost added metres to metres-per-second and mixed a per-node value with a
    # path value, which made the weights impossible to reason about.
    # Sized so that giving up the whole margin costs several steps of progress,
    # otherwise the goal gradient simply buys its way through the margin and the path
    # ends up grazing the hard constraint instead of sitting off it.
    CLEARANCE_MAGNET_WEIGHT: float = 6.0
    # How much more cheaply passing wide is charged than passing too close, and how far
    # out the "too wide" penalty keeps growing before it saturates (in safety radii).
    FAR_SIDE_FRACTION: float = 0.25
    FAR_CLEARANCE_CAP_FRACTION: float = 2.0
    WRONG_SIDE_WEIGHT: float = 6.0
    # Per-step, and therefore bounded by what a step of progress is worth (1.0 in
    # leaf_cost's units). Their worst case sum has to stay comfortably under that or
    # every extra node costs more than it gains and the search returns a stub instead of
    # a trajectory: at a combined 4.6 a single readily apparent turn cost three steps of
    # progress, so the cheapest path was to barely move at all.
    CURVATURE_WEIGHT: float = 0.15
    TURN_RATE_CHANGE_WEIGHT: float = 0.35
    # Charged once, on how many more steps of travel separate the path's end from the
    # goal. This is the only term that grows with distance, so it is what makes the
    # search press on rather than stop early, without paying for aimless motion.
    GOAL_WEIGHT: float = 1.0
    # Charged once, on the final heading error against the original course. See leaf_cost.
    COURSE_RESUMPTION_WEIGHT: float = 8.0
    # What fraction of that weight still applies while an encounter is unresolved. It
    # cannot pull the vessel back onto its course there, because HoldAvoidanceCourseRule
    # forbids the reverse turn outright; all it does is price the SIZE of the alteration,
    # so the search prefers the smallest deviation that clears the other vessel. At zero
    # a detour of any size was free once an encounter existed and the planner produced
    # 115 deg turns that then failed Rule 8 against a third vessel.
    IN_ENCOUNTER_RESUMPTION_FRACTION: float = 0.5
    # Where the magnet sits, as a fraction of the actor's safety radius outside the
    # domain boundary. Zero would park the path exactly on the hard constraint, so most
    # successors would be rejected and the search would thrash.
    CLEARANCE_MARGIN_FRACTION: float = 0.5

    @property
    def clearance_margin(self) -> float:
        return self.CLEARANCE_MARGIN_FRACTION * max(self.actor.safety_radius, EPSILON)

    def step_cost(self, parent: SceneNode, node: SceneNode) -> float:
        """Cost of the one step from ``parent`` to ``node``, for this actor.

        Accumulated along the path by ``SceneNode.path_cost``. Evaluating the cost only
        at the leaf made a path that cut through a domain and came back score the same
        as one that went around it.
        """
        max_heading_step = max(self.actor.get_max_heading_step(self.time_step), EPSILON)

        # Only local, bounded terms belong here. Anything charged per node and unbounded
        # makes a short path automatically cheaper than a long one, and the search then
        # returns a two-scene stub.
        cost = 0.0

        # Curvature and change of curvature: what actually buys a smooth arc.
        heading_step = node.heading_steps.get(self.actor, 0.0)
        previous_heading_step = parent.heading_steps.get(self.actor, heading_step)
        cost += self.CURVATURE_WEIGHT * abs(heading_step) / max_heading_step
        cost += self.TURN_RATE_CHANGE_WEIGHT * abs(heading_step - previous_heading_step) / max_heading_step

        # Deliberately no reward for distance travelled. Paying per metre covered makes
        # flying in circles profitable: the reward accrues every step while the distance
        # to the goal barely changes. Length is instead made cost neutral by leaving g
        # free of any length term, so a longer path is preferred exactly when it ends
        # nearer the goal, which is what leaf_cost measures.
        return cost

    def leaf_cost(self, node: SceneNode) -> float:
        """Cost of the path as a whole, charged once at its end.

        Two kinds of term live here. The magnet and side terms are about the closest
        point of approach, which is a property of the path, not of each node. The goal
        term is the estimated cost still to come, in the same per-step units as
        ``step_cost``'s progress reward, so that comparing a short path against a long
        one is meaningful.
        """
        scale = max(self.actor.safety_radius, EPSILON)
        cost = 0.0

        # Magnet: of the paths that stay legal, prefer the one whose closest approach
        # sits at the target margin outside the domain boundary. Being needlessly far
        # out costs the same as crowding the boundary, and a path that starts inside
        # the domain is pulled out because its minimum clearance is negative.
        min_clearance = node.min_clearance.get(self.actor)
        if min_clearance is not None:
            # Asymmetric and saturating. A symmetric magnet punishes distance from the
            # boundary as hard as crowding it, which makes steering INTO the encounter
            # cheap: it will happily add a large detour toward the other vessel just to
            # bring its closest approach down to the margin. Coming up short is what
            # matters, so that side is charged at full weight and without limit, while
            # passing wide is charged gently and stops growing past the cap. What keeps
            # the path against the boundary from the outside is this plus the goal term,
            # which already prices any detour.
            deficit = max(0.0, self.clearance_margin - min_clearance)
            excess = min(max(0.0, min_clearance - self.clearance_margin), self.FAR_CLEARANCE_CAP_FRACTION * scale)
            cost += self.CLEARANCE_MAGNET_WEIGHT * deficit / scale
            cost += self.CLEARANCE_MAGNET_WEIGHT * self.FAR_SIDE_FRACTION * excess / scale

            # Side: clearance is direction blind, so on its own the magnet is equally
            # happy either side of the domain. This is what puts the avoidance on the
            # side the encounter calls for, judged at the closest point of approach.
            side_offset = node.side_offset_at_min_clearance.get(self.actor, 0.0)
            if side_offset < 0.0:
                cost += self.WRONG_SIDE_WEIGHT * (-side_offset) / scale

        # Cost to go, counted in steps still to travel AT THE CURRENT SPEED. Using
        # max_speed here would understate a step's worth (a vessel at half throttle
        # would gain only half a unit per step), and the per-step costs in step_cost are
        # calibrated against a full unit of progress being worth one step.
        state = node.scene[self.actor]
        reachable = max(state.speed * self.time_step, EPSILON)
        to_goal = self.goal_position_at(node) - state.p
        resolved = self.is_resolved(node)

        # Split the vector to the goal along the original course and across it. The goal
        # sits on that course, so the across component is exactly the vessel's cross-track
        # offset. Straight-line distance hides that offset inside a hypotenuse whose base
        # is the whole planning horizon: against a goal 35 km ahead, being 2.2 km off
        # track adds 69 m, well under one step of progress, so the search had no reason to
        # rejoin and simply ran parallel to its original track for the rest of the plan.
        # Charged separately, closing the gap costs what it actually costs, which is the
        # steps needed to travel it.
        along_to_goal = max(float(np.dot(to_goal, self.forward)), 0.0)
        cross_track = abs(float(np.dot(to_goal, self.across)))

        # Charged at every node, resolved or not. Gating it on resolution puts a cliff in
        # the cost exactly where the encounter ends: a resolved node a kilometre off track
        # suddenly costs ten more units than an unresolved one, so the search simply
        # declines to resolve anything and returns a stub that stops mid-encounter. What
        # keeps a vessel from trading its avoidance course back for a smaller offset is
        # HoldAvoidanceCourseRule, which forbids it outright; that belongs in a rule, not
        # in a discontinuity in the objective.
        cost += self.GOAL_WEIGHT * (along_to_goal + cross_track) / reachable

        if resolved:
            # Steer at the goal, so the heading term asks the vessel to close the offset
            # rather than to sit parallel to its original course.
            distance_to_goal = float(np.hypot(to_goal[0], to_goal[1]))
            reference_heading = calculate_heading(to_goal) if distance_to_goal > EPSILON else self.start_state.heading
        else:
            # While the encounter is live the reference stays the original course, so this
            # term prices how far the vessel has strayed without asking it to come back.
            reference_heading = self.start_state.heading

        # Resume course once the encounter is behind. At full weight this is the largest
        # term in the objective, and charging it during an encounter is what made the
        # search take its avoidance turn and undo it within a couple of steps, long before
        # the pair had passed: an alteration taken back mid-encounter is not readily
        # apparent to the vessel it was made for. While anything is still unresolved only
        # a fraction of it applies, which no longer buys the turn back
        # (HoldAvoidanceCourseRule forbids that outright) but still prices how far the
        # vessel strays. Once every encounter has resolved the full weight returns, which
        # is what produces the resumption, and what keeps going round in circles strictly
        # worse than pressing on.
        heading_error = abs(heading_diff(state.heading, reference_heading))
        resumption_weight = self.COURSE_RESUMPTION_WEIGHT if resolved else self.COURSE_RESUMPTION_WEIGHT * self.IN_ENCOUNTER_RESUMPTION_FRACTION
        cost += resumption_weight * heading_error / np.pi

        return cost

    def reached_goal(self, node: SceneNode) -> bool:
        """True once this actor's trajectory has the shape it was asked for.

        Arriving at the end point is sufficient but not necessary. What is actually
        wanted is the finished hill: the encounter behind, the vessel back on its
        original track, and steady on its original course. Testing only the end point
        would make success depend on an estimate rather than on the behaviour, and the
        estimate is deliberately conservative.
        """
        state = node.scene[self.actor]
        reach = max(self.actor.distance_made(state, (state.heading, state.speed), self.time_step), EPSILON)
        if distance(state.p, self.goal_position_at(node)) <= reach:
            return True
        if not self.is_past_encounter(node):
            return False
        if abs(self.cross_track(state)) > self.REJOIN_TOLERANCE_FRACTION * max(self.actor.safety_radius, EPSILON):
            return False
        colregs_constants = node.maneuver_state_set[self.relation].colregs_constants
        if abs(heading_diff(state.heading, self.start_state.heading)) > colregs_constants.UNDETECTABLE_HEADING_CHANGE:
            return False
        # Being on track before the encounter has been run past is not a finished hill,
        # it is a hill that has not started.
        return self.along_track(state) >= self.start_resolve_distance

    def is_past_encounter(self, node: SceneNode) -> bool:
        """True once this actor has been in a COLREGS situation and left it behind.

        Not the same as ``is_resolved``, which is also true before the first encounter
        latches. Everything about resuming the original course has to key on this one:
        keying on ``is_resolved`` forbids the avoidance manoeuvre itself, because at t=0
        every situation is still classified OTHER.
        """
        return self.actor in node.encountered and self.is_resolved(node)

    def is_resolved(self, node: SceneNode) -> bool:
        """True when this actor has no encounter left to resolve."""
        for situation_context, colregs_state in node.monitored_scene_with_results.colregs_states_with_context:
            if self.actor not in situation_context.actors:
                continue
            if situation_context.situation_type is COLREGSType.OTHER:
                continue
            if not colregs_state.actors_passed_each_other:
                return False
        return True

    def rejoin_admissible(self, parent: SceneNode, node: SceneNode) -> bool:
        """False when an actor that is past its encounters turns further off its track.

        This is the "as soon as possible" half of the resumption, and it is a search
        constraint rather than a cost term on purpose. Pricing it cannot work: the cost
        already charges cross-track at the largest weight in the objective and the
        vessel still ran parallel, because the manoeuvre that would rejoin was never in
        the sampled action set. It is also not a COLREGS rule: rejoining your own track
        is scenario intent, not a Rule 8 obligation, and putting it in the monitor would
        show a lawful path as a rule failure in the console.

        The test is on the TURN, not on the offset. Constraining the offset directly
        rejects every successor and dead-ends the branch: from 28 deg off course the
        largest admissible correction in one step is a readily apparent 15.3 deg, which
        still leaves the vessel diverging, so the first step of the return always makes
        the offset worse and the manoeuvre can never be started. What is actually wanted
        is that the vessel never turns AWAY from its track once the encounter is behind
        it, which is a condition on the heading step and is satisfiable in one step.

        Rejecting a successor is not the same as a cliff in the cost: the node simply
        does not exist, so there is nothing for the search to trade against.
        """
        if not self.is_past_encounter(node):
            return True
        state = node.scene[self.actor]
        offset = self.cross_track(state)
        tolerance = self.REJOIN_TOLERANCE_FRACTION * max(self.actor.safety_radius, EPSILON)
        if abs(offset) <= tolerance:
            # Already on track. Holding it means small excursions either side, so the
            # constraint has to stop applying inside the tolerance or the vessel could
            # never correct back across the line.
            return True

        if abs(offset) <= abs(self.cross_track(parent.scene[self.actor])):
            # The gap is already closing, so whatever it just did is working.
            return True
        # Still opening. Admissible only if this step turned toward the track.
        #
        # This stops the offset growing; it does NOT make the vessel rejoin promptly,
        # because a 2 deg lean counts as closing and takes hours to cover 2 km. Requiring
        # a real closing RATE here is the missing half, and it cannot be added yet:
        # StandOnCoursePersistenceCondition offers a vessel with no live encounter only
        # PERSISTING_COURSE (plus or minus 2 deg), so the readily apparent turn a real
        # rejoin needs is not in the action set at all and the requirement is
        # unsatisfiable. Imposing it anyway refused every successor and left the planner
        # stalled on a 30 step path.
        closing_sign = -np.sign(offset)
        return float(node.heading_steps.get(self.actor, 0.0)) * closing_sign >= -EPSILON


class TrajectoryObjectiveSet(Dict[ConcreteActor, TrajectoryObjective]):
    # How many heading magnitudes to draw from each suggested sub-interval.
    SAMPLES_PER_INTERVAL: int = 3
    # How much the per-step heading change may differ from the previous step, as a
    # fraction of the vessel's full heading range. Lower means smoother, less agile.
    MAX_TURN_RATE_CHANGE: float = 0.35
    # Ceiling on the children generated per expansion. The joint action space is the
    # product over actors, so without this a 3 vessel scene branches by hundreds.
    MAX_CHILDREN_PER_EXPANSION: int = 12

    def __init__(
        self,
        root: SceneNode,
        time_step: int,
        goal_sample_rate: int,
        verbose: bool = False,
        samples_per_interval: Optional[int] = None,
        max_turn_rate_change: Optional[float] = None,
        max_children_per_expansion: Optional[int] = None,
        goal_horizon: float = 0.0,
    ):
        # Only vessels are steerable and only vessels have maneuver states; static
        # obstacles stay in the scene untouched (see TrajectoryTreeBuilder.steer_actors).
        super().__init__({actor: TrajectoryObjective(actor, root, time_step, verbose, goal_horizon) for actor in root.scene.vessels})
        # Seed the root with the estimate made at the root. Every other node inherits
        # from its parent through update_goal_distances.
        for actor, trajectory_objective in self.items():
            root.goal_distances[actor] = trajectory_objective.start_goal_distance
        self.goal_sample_rate = goal_sample_rate
        self.time_step = time_step
        self.samples_per_interval = self.SAMPLES_PER_INTERVAL if samples_per_interval is None else samples_per_interval
        self.max_turn_rate_change = self.MAX_TURN_RATE_CHANGE if max_turn_rate_change is None else max_turn_rate_change
        self.max_children_per_expansion = self.MAX_CHILDREN_PER_EXPANSION if max_children_per_expansion is None else max_children_per_expansion

    def calculate_step_cost(self, parent: SceneNode, node: SceneNode) -> float:
        return sum(trajectory_objective.step_cost(parent, node) for trajectory_objective in self.values())

    def calculate_cost(self, node: SceneNode) -> float:
        """Total cost of the path ending at ``node``: accumulated steps plus the leaf term."""
        return node.path_cost + sum(trajectory_objective.leaf_cost(node) for trajectory_objective in self.values())

    def is_resolved(self, node: SceneNode) -> bool:
        return all(trajectory_objective.is_resolved(node) for trajectory_objective in self.values())

    def reached_goal(self, node: SceneNode) -> bool:
        return all(trajectory_objective.reached_goal(node) for trajectory_objective in self.values())

    def update_path_state(self, parent: SceneNode, node: SceneNode) -> None:
        """Carry the per-path state onto ``node``.

        The end point is raised whenever a new COLREGS situation makes the inherited one
        too short, and left alone otherwise.
        """
        for actor, trajectory_objective in self.items():
            node.goal_distances[actor] = trajectory_objective.updated_goal_distance(parent, node)

    def rejoin_admissible(self, parent: SceneNode, node: SceneNode) -> bool:
        return all(trajectory_objective.rejoin_admissible(parent, node) for trajectory_objective in self.values())

    def get_suggested_headings(self, node: SceneNode) -> List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
        suggested_headings: Dict[ConcreteActor, List[float]] = {}
        heading_changes: Dict[ConcreteActor, List[float]] = {}
        suggested_maneuvers = node.maneuver_suggestions
        for actor, trajectory_objective in self.items():
            state = node.scene[actor]
            colregs_constants = node.maneuver_state_set[Relation(actor, actor)].colregs_constants
            suggested_ranges = suggested_maneuvers.get_suggested_range_of_heading_change(actor, trajectory_objective.time_step, colregs_constants)

            if trajectory_objective.verbose:
                print(f"{actor.name}: Suggested maneuvers: {suggested_maneuvers.get_all_maneuvers(actor)}")
                print(f"{actor.name}: Suggested maneuvers info: {suggested_maneuvers.get_info(actor)}")
                print(f"{actor.name}: Suggested ranges: {suggested_ranges}")

            if suggested_ranges.empty:
                if trajectory_objective.verbose:
                    print(f"WARNING: No suggested ranges found for {actor.name}")
                return []

            # Keep the turn rate continuous: a step may not differ from the previous one
            # by more than MAX_TURN_RATE_CHANGE of the full range. Without this a 3 deg
            # step can be followed by a 25 deg one and the path kinks at every node.
            suggested_ranges = self._bound_turn_rate_change(node, actor, suggested_ranges)
            if suggested_ranges.empty:
                if trajectory_objective.verbose:
                    print(f"WARNING: Turn rate continuity left no range for {actor.name}")
                return []

            if self.goal_sample_rate > random.randint(0, 100):
                to_goal_heading = calculate_heading(trajectory_objective.aim_point(node) - state.p)
                to_goal_heading_diff = heading_diff(to_goal_heading, state.heading)
                # The bounds must be ordered: a goal to starboard gives a negative diff and
                # Interval.closed(0, negative) is empty, which silently turned every
                # starboard-biased sample into "hold course exactly".
                to_goal_heading_change_interval = Interval.closed(min(0.0, to_goal_heading_diff), max(0.0, to_goal_heading_diff))
                if to_goal_heading_change_interval.empty:
                    to_goal_heading_change_interval = Interval.closed(-EPSILON, EPSILON)
                goal_ranges = suggested_ranges.intersection(to_goal_heading_change_interval)
                # Goal biasing is a heuristic: when no suggested manoeuvre points at the
                # goal, fall back to the unbiased suggestion instead of yielding nothing.
                random_heading_changes = (suggested_ranges if goal_ranges.empty else goal_ranges).sample_from_all(self.samples_per_interval)
                if trajectory_objective.verbose and False:
                    print(f"{actor.name}: To goal heading change interval: {to_goal_heading_change_interval}")
                    print(f"{actor.name}: Suggested ranges after goal sample: {goal_ranges}")
            else:
                random_heading_changes = suggested_ranges.sample_from_all(self.samples_per_interval)

            heading_changes[actor] = random_heading_changes
            suggested_headings[actor] = [rotate_heading(state.heading, change) for change in random_heading_changes]

        # convert to List[Dict[ConcreteActor, float]] by taking the product of the suggested ranges
        return self.combine_headings(suggested_headings, heading_changes, self.max_children_per_expansion)

    def _bound_turn_rate_change(self, node: SceneNode, actor: ConcreteActor, suggested_ranges: Interval) -> Interval:
        """Restrict this step's heading change to stay near the previous step's.

        The parent's heading step is the current turn rate; allowing the next one to be
        anything inside the suggested range is what produces a polyline. Limiting how
        much the rate may change per step is what makes the result an arc. The root has
        no previous step, so it is left unconstrained.
        """
        previous_change = node.heading_steps.get(actor)
        if previous_change is None:
            return suggested_ranges
        max_heading_step = actor.get_max_heading_step(self.time_step)
        if max_heading_step <= 0:
            return suggested_ranges

        allowance = self.max_turn_rate_change * max_heading_step
        window = Interval.closed(previous_change - allowance, previous_change + allowance)

        # Applied per sub-interval, not to the union. Each sub-interval is one manoeuvre
        # type, and intersecting the union would delete a whole manoeuvre whenever it
        # lies outside the window: a vessel holding course could then never START a
        # readily apparent alteration, which is the opposite of what Rule 8 asks for.
        # Within a manoeuvre the window smooths the turn rate; to enter a different
        # manoeuvre the nearest admissible magnitude is offered instead.
        bounded_parts: List[Interval] = []
        for atomic in suggested_ranges:
            part = Interval(atomic)
            trimmed = part.intersection(window)
            if not trimmed.empty:
                bounded_parts.append(trimmed)
                continue
            # Clamp to the endpoint nearest the window. Interval.crop returns the lower
            # of the two bounds rather than the closer one, which would offer the most
            # violent version of the manoeuvre instead of the gentlest admissible one.
            nearest = min(atomic.upper, max(atomic.lower, previous_change))
            bounded_parts.append(Interval.closed(nearest, nearest))

        if not bounded_parts:
            return suggested_ranges
        return Interval(*bounded_parts)

    @staticmethod
    def combine_headings(
        headings: Dict[ConcreteActor, List[float]],
        heading_changes: Dict[ConcreteActor, List[float]],
        max_combinations: Optional[int] = None,
    ) -> List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
        if not headings:
            return []

        # Compute Cartesian product of headings, carrying the heading change that
        # produced each one so the successor node can record its own turn rate.
        actors = list(headings.keys())
        lists = [list(zip(headings[a], heading_changes[a])) for a in actors]

        result = []
        for combo in product(*lists):
            entry = {actor: heading for actor, (heading, _) in zip(actors, combo)}
            changes = {actor: change for actor, (_, change) in zip(actors, combo)}
            result.append((entry, changes))

        # The product grows as (samples per actor) ** (number of actors), so sampling
        # several magnitudes per interval explodes the branching factor for a multi
        # vessel scene. Cap it, keeping a random subset so no particular combination is
        # systematically favoured.
        if max_combinations is not None and len(result) > max_combinations:
            result = random.sample(result, max_combinations)

        return result


class TrajectoryTreeBuilder:
    def __init__(self, root_scene: ConcreteScene, time_step: int, monitor_set: COLREGSMonitor):
        self._next_node_id = 0
        self.node_list: Dict[int, SceneNode] = {}
        self.root = SceneNode(monitored_scene_with_results=monitor_set.initial_monitored_scene_with_results)
        self.add_node(None, self.root)
        self.time_step = time_step
        self.monitor = monitor_set

    def add_node(self, parent: Optional[SceneNode], node: SceneNode):
        new_node_id = self._next_node_id
        self._next_node_id += 1
        self.node_list[new_node_id] = node
        node.id = new_node_id
        if parent is not None:
            parent.add_child(node)

    @property
    def leaves(self) -> List[SceneNode]:
        return [node for node in self.nodes if len(node.children) == 0]

    @property
    def nodes(self) -> List[SceneNode]:
        return list(self.node_list.values())

    @property
    def expandable_leaves(self) -> List[SceneNode]:
        return [node for node in self.leaves if not node.is_dead_end]

    @property
    def expandable_nodes(self) -> List[SceneNode]:
        return [node for node in self.nodes if not node.is_dead_end]

    def __len__(self):
        return len(self.node_list)

    def node(self, id: int) -> SceneNode:
        return self.node_list[id]

    def parent(self, node: SceneNode) -> SceneNode:
        if node.parent is None:
            raise ValueError("Node is root")
        return self.node_list[node.parent]

    def get_path(self, node: SceneNode) -> List[SceneNode]:
        path = []
        node_to_add = node
        while not node_to_add.is_root:
            path.append(node_to_add)
            node_to_add = self.parent(node_to_add)
        path.append(node_to_add)
        path.reverse()
        return path

    def get_path_trajectories(self, node: SceneNode) -> Tuple[Trajectories, List[SceneNode]]:
        node_path = self.get_path(node)
        builder = TrajectoryBuilder(scene_list=[node.scene for node in node_path], time_step=self.time_step)
        return builder.build(), node_path

    def get_monitored_trajectory(self, node: SceneNode) -> MonitoredTrajectory:
        node_path = self.get_path(node)
        monitored_trajectory = MonitoredTrajectory(time_step=self.time_step)
        for node in node_path:
            monitored_trajectory.add_scene(node.monitored_scene_with_results)
        return monitored_trajectory

    def remove_branch(self, node: SceneNode) -> None:
        if node.is_root:
            return

        self.parent(node).remove_child(node)
        # remove all children of the node recursively
        list_of_children = self.get_all_children_recursively(node) + [node]
        for child in list_of_children:
            self.node_list.pop(child.id, None)

    def get_all_children_recursively(self, node: SceneNode) -> List[SceneNode]:
        children = []
        for child in node.children:
            children.append(self.node(child))
            children.extend(self.get_all_children_recursively(self.node(child)))
        return children

    @property
    def lastly_added_node(self) -> SceneNode:
        return self.node(self._next_node_id - 1)

    @property
    def random_node(self) -> SceneNode:
        return random.choice(self.nodes)

    def random_nodes(self, k: int) -> List[SceneNode]:
        if len(self.nodes) < k:
            return self.nodes
        return random.sample(self.nodes, k)

    def random_node_on_path(self, node: SceneNode) -> SceneNode:
        path = self.get_path(node)
        return random.choice(path)

    @property
    def random_leaf(self) -> SceneNode:
        return random.choice(self.leaves)

    def random_leafs(self, k: int) -> List[SceneNode]:
        if len(self.leaves) < k:
            return self.leaves
        return random.sample(self.leaves, k)

    def remove_branch_until_parent_with_multiple_children(self, node: SceneNode) -> None:
        # Find the node to remove: traverse up until we find a parent with multiple children
        iter_node = node
        branch_to_remove = None
        while not iter_node.is_root:
            parent = self.parent(iter_node)
            if len(parent.children) > 1:
                branch_to_remove = iter_node
                break
            iter_node = parent

        if branch_to_remove is not None:
            self.remove_branch(branch_to_remove)

    def prune_branches(self) -> None:
        """Remove a random leaf node to keep the tree size bounded.

        Prefer removing a leaf whose parent has multiple children to preserve
        connectivity; otherwise, remove any leaf.
        """
        # Prefer leaves whose parent is a branching node
        preferred_leaves: List[int] = [key for key, node in self.node_list.items() if len(node.children) == 0 and node.parent is not None and len(self.node_list[node.parent].children) > 1]
        candidate_leaves: List[int]
        if len(preferred_leaves) > 0:
            candidate_leaves = preferred_leaves
        else:
            candidate_leaves = [key for key, node in self.node_list.items() if len(node.children) == 0]

        if not candidate_leaves:
            return

        ind = random.choice(candidate_leaves)
        parent = self.node_list[ind].parent
        if parent is not None and parent in self.node_list:
            self.node_list[parent].children.discard(ind)
        self.node_list.pop(ind, None)

    def steer_actors(self, nearest_node: SceneNode, trajectory_objective_set: TrajectoryObjectiveSet) -> List[SceneNode]:
        suggested_headings = trajectory_objective_set.get_suggested_headings(nearest_node)
        new_nodes = []
        for headings, heading_changes in suggested_headings:
            # Seed from the current scene so actors that are not steered (static
            # obstacles) stay in the scene; only the steered actors are overwritten.
            next_scene = SceneBuilder(nearest_node.scene)
            for actor, heading in headings.items():
                actor_state = nearest_node.scene[actor]
                next_state = actor.simulate(actor_state, (heading, actor_state.speed), self.time_step)
                next_scene.set_state(actor, next_state)
            monitored_scene_with_results = self.monitor.step(nearest_node.monitored_scene_with_results, next_scene.build(), self.time_step)
            next_node = SceneNode(monitored_scene_with_results=monitored_scene_with_results)
            next_node.heading_steps = dict(heading_changes)
            next_node.inherit_running_extremes(nearest_node)
            trajectory_objective_set.update_path_state(nearest_node, next_node)
            next_node.path_cost = nearest_node.path_cost + trajectory_objective_set.calculate_step_cost(nearest_node, next_node)
            new_nodes.append(next_node)
        return new_nodes

    def get_best_leafs(self, trajectory_objective: TrajectoryObjective, k: int) -> List[SceneNode]:
        """Get the k nearest nodes to the point in increasing order of distance."""
        nodes = self.leaves
        nodes.sort(key=lambda node: trajectory_objective.calculate_cost(node))
        return nodes[:k]

    def get_best_nodes(self, trajectory_objective: TrajectoryObjective, k: int) -> List[SceneNode]:
        nodes = self.nodes
        nodes.sort(key=lambda node: trajectory_objective.calculate_cost(node))
        return nodes[:k]

    def get_best_node(self, trajectory_objective: TrajectoryObjective) -> SceneNode:
        return self.get_best_nodes(trajectory_objective, 1)[0]

    def get_best_random_node(self, trajectory_objective: TrajectoryObjective, k: int) -> SceneNode:
        nodes = self.get_best_nodes(trajectory_objective, k)
        return random.choice(nodes)

    def prune_worst_leaves(self, trajectory_objective: TrajectoryObjective, k: int) -> None:
        for node in self.get_worst_leafs(trajectory_objective, k):
            self.remove_branch(node)

    def prune_worst_leaves_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> None:
        for node in self.get_worst_leafs_global(trajectory_objective_set, k):
            self.remove_branch(node)

    def get_worst_leafs(self, trajectory_objective: TrajectoryObjective, k: int) -> List[SceneNode]:
        """Get the k furthest nodes to the point in decreasing order of distance."""
        nodes = self.leaves
        nodes.sort(key=lambda node: trajectory_objective.calculate_cost(node), reverse=True)
        return nodes[:k]

    def get_best_leafs_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.leaves
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]

    def get_best_leaf_global(self, trajectory_objective_set: TrajectoryObjectiveSet) -> SceneNode:
        return self.get_best_leafs_global(trajectory_objective_set, 1)[0]

    def get_worst_leafs_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.leaves
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node), reverse=True)
        return nodes[:k]

    def get_best_node_global(self, trajectory_objective_set: TrajectoryObjectiveSet) -> SceneNode:
        return self.get_best_nodes_global(trajectory_objective_set, 1)[0]

    def get_best_nodes_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.nodes
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]

    def get_worst_nodes_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.nodes
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node), reverse=True)
        return nodes[:k]

    def get_best_expandable_leafs_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        """Best leaves that can still be steered from. Dead ends stay on the tree for
        path extraction but are never handed back for expansion."""
        nodes = self.expandable_leaves
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]

    def get_best_expandable_nodes_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.expandable_nodes
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]
