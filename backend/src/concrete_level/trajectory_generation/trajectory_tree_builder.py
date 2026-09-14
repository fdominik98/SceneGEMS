import random
from dataclasses import dataclass
from itertools import product
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import (
    READILY_APPARENT_PLANNING_MARGIN,
    ManeuverStateSet,
    get_suggested_range_of_heading_change_for_persisting_course,
)
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults, MonitoredTrajectory
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.maneuvering_domain import ManeuveringDomain
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON, MAX_DISTANCE
from utils.interval import Interval
from utils.math_utils import distance, heading_diff, rotate_heading


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
        self.heading_steps: Dict[ConcreteActor, float] = {}
        self.path_cost: float = 0.0
        self.window_depth: int = 0
        # Per-actor end point, as a distance along the actor's ORIGINAL course measured
        # from its start state. Inherited from the parent and only ever raised.
        self.goal_distances: Dict[ConcreteActor, float] = {}
        # Actors that have been in a COLREGS situation anywhere on the path so far.
        self.encountered: Set[ConcreteActor] = set()
        self._record_encounters()

    def _record_encounters(self) -> None:
        for situation_context, _colregs_state in self.monitored_scene_with_results.colregs_states_with_context:
            if situation_context.situation_type is COLREGSType.OTHER:
                continue
            self.encountered.update(situation_context.actors)

    def inherit_running_extremes(self, parent: "SceneNode") -> None:
        self.encountered = set(parent.encountered)
        self._record_encounters()

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


@dataclass
class WindowRepairSpec:
    seed_nodes: List["SceneNode"]
    start: int
    end: int
    free_actors: Set[ConcreteActor]
    rejoin_scene: ConcreteScene
    rejoin_tolerance: float

    @property
    def length(self) -> int:
        return self.end - self.start

    def locked_state(self, depth: int, actor: ConcreteActor) -> ActorState:
        index = min(self.start + depth + 1, self.end)
        return self.seed_nodes[index].scene[actor]

    def locked_heading_change(self, depth: int, actor: ConcreteActor) -> float:
        index = min(self.start + depth + 1, self.end)
        return self.seed_nodes[index].heading_steps.get(actor, 0.0)


class TrajectoryObjective:
    SETTLE_STEPS: int = 3
    TRACK_TOLERANCE_FRACTION: float = 1.0
    LINE_MAGNET_WEIGHT: float = 6.0
    GOAL_WEIGHT: float = 1.0

    def __init__(self, actor: ConcreteActor, root: SceneNode, time_step: int, verbose: bool = False, goal_horizon: float = 0.0):
        self.actor = actor
        self.relation = Relation(actor, actor)
        self.time_step = time_step
        self.start_state = root.scene[self.actor]
        self.verbose = verbose
        self.forward = np.array([np.cos(self.start_state.heading), np.sin(self.start_state.heading)])
        self.across = np.array([-np.sin(self.start_state.heading), np.cos(self.start_state.heading)])
        self.horizon_distance = self.actor.distance_made(self.start_state, (self.start_state.heading, self.start_state.speed), max(goal_horizon, time_step))
        self._domain_cache: Dict[int, Optional[ManeuveringDomain]] = {}
        self.start_goal_distance = self.estimate_goal_distance(root)
        self.goal_position = self.start_state.p + self.forward * self.start_goal_distance

    def along_track(self, state: ActorState) -> float:
        return float(np.dot(state.p - self.start_state.p, self.forward))

    def cross_track(self, state: ActorState) -> float:
        """Signed offset from the original track, positive to port of it."""
        return float(np.dot(state.p - self.start_state.p, self.across))

    def estimate_goal_distance(self, node: SceneNode) -> float:
        settle = self.SETTLE_STEPS * node.scene[self.actor].speed * self.time_step
        far = self._furthest_far_along(node)
        goal_distance = max(far + settle, settle)
        return float(min(goal_distance, self.horizon_distance, MAX_DISTANCE))

    def goal_distance(self, node: SceneNode) -> float:
        return node.goal_distances.get(self.actor, self.start_goal_distance)

    def goal_position_at(self, node: SceneNode) -> np.ndarray:
        return self.start_state.p + self.forward * self.goal_distance(node)

    def updated_goal_distance(self, parent: SceneNode, node: SceneNode) -> float:
        inherited = self.goal_distance(parent)
        if self.is_past_encounter(node):
            return inherited
        return max(inherited, self.estimate_goal_distance(node))

    def maneuvering_domains_for(self, node: SceneNode) -> List[ManeuveringDomain]:
        along = self.along_track(node.scene[self.actor])
        domain = self._union_domain(node)
        if domain is None or along > domain.far_along:
            return []
        return [domain]

    def step_cost(self, parent: SceneNode, node: SceneNode) -> float:
        del parent
        scale = max(self.actor.safety_radius, EPSILON)
        point = node.scene[self.actor].p
        domains = self.maneuvering_domains_for(node)
        if domains:
            return sum(domain.magnet_cost(point, scale) for domain in domains)
        return self.LINE_MAGNET_WEIGHT * min(abs(self.cross_track(node.scene[self.actor])), ManeuveringDomain.FAR_CAP_FRACTION * scale) / scale

    def leaf_cost(self, node: SceneNode) -> float:
        state = node.scene[self.actor]
        reachable = max(state.speed * self.time_step, EPSILON)
        along_to_goal = max(self.goal_distance(node) - self.along_track(state), 0.0)
        return self.GOAL_WEIGHT * along_to_goal / reachable

    def calculate_cost(self, node: SceneNode) -> float:
        return node.path_cost + self.leaf_cost(node)

    def reached_goal(self, node: SceneNode) -> bool:
        state = node.scene[self.actor]
        reach = max(self.actor.distance_made(state, (state.heading, state.speed), self.time_step), EPSILON)
        if distance(state.p, self.goal_position_at(node)) <= reach:
            return True
        if not self.is_past_encounter(node):
            return False
        if self.along_track(state) < self._furthest_far_along(node):
            return False
        tolerance = self.TRACK_TOLERANCE_FRACTION * max(self.actor.safety_radius, EPSILON)
        if abs(self.cross_track(state)) > tolerance:
            return False
        colregs_constants = node.maneuver_state_set[self.relation].colregs_constants
        return abs(heading_diff(state.heading, self.start_state.heading)) <= colregs_constants.UNDETECTABLE_HEADING_CHANGE

    def is_past_encounter(self, node: SceneNode) -> bool:
        return self.actor in node.encountered and self.is_resolved(node)

    def is_resolved(self, node: SceneNode) -> bool:
        for situation_context, colregs_state in node.monitored_scene_with_results.colregs_states_with_context:
            if self.actor not in situation_context.actors:
                continue
            if situation_context.situation_type is COLREGSType.OTHER:
                continue
            if not colregs_state.actors_passed_each_other:
                return False
        return True

    def _furthest_far_along(self, node: SceneNode) -> float:
        domain = self._union_domain(node)
        return 0.0 if domain is None else domain.far_along

    def _union_domain(self, node: SceneNode) -> Optional[ManeuveringDomain]:
        key = id(node.monitored_scene_with_results.situation_context_set)
        if key not in self._domain_cache:
            contexts = list(node.monitored_scene_with_results.situation_context_set.values())
            self._domain_cache[key] = ManeuveringDomain.for_give_way_ship(self.actor, contexts)
        return self._domain_cache[key]


class TrajectoryObjectiveSet(Dict[ConcreteActor, TrajectoryObjective]):
    SAMPLES_PER_INTERVAL: int = 3
    MAX_CHILDREN_PER_EXPANSION: int = 12
    REJOIN_WEIGHT: float = 8.0
    REMAINING_STEP_WEIGHT: float = 0.25

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
        del max_turn_rate_change
        super().__init__({actor: TrajectoryObjective(actor, root, time_step, verbose, goal_horizon) for actor in root.scene.vessels})
        for actor, trajectory_objective in self.items():
            root.goal_distances[actor] = trajectory_objective.start_goal_distance
        self.goal_sample_rate = goal_sample_rate
        self.time_step = time_step
        self.samples_per_interval = self.SAMPLES_PER_INTERVAL if samples_per_interval is None else samples_per_interval
        self.max_children_per_expansion = self.MAX_CHILDREN_PER_EXPANSION if max_children_per_expansion is None else max_children_per_expansion
        self.window_spec: Optional[WindowRepairSpec] = None

    def calculate_step_cost(self, parent: SceneNode, node: SceneNode) -> float:
        return sum(objective.step_cost(parent, node) for actor, objective in self.items() if self._is_costed(actor))

    def calculate_cost(self, node: SceneNode) -> float:
        leaf = sum(objective.leaf_cost(node) for actor, objective in self.items() if self._is_costed(actor))
        return node.path_cost + leaf + self._window_search_cost(node)

    def _is_costed(self, actor: ConcreteActor) -> bool:
        spec = self.window_spec
        return spec is None or actor in spec.free_actors

    def _window_search_cost(self, node: SceneNode) -> float:
        spec = self.window_spec
        if spec is None:
            return 0.0
        remaining = max(spec.length - node.window_depth, 0)
        cost = self.REMAINING_STEP_WEIGHT * remaining
        if node.window_depth >= spec.length:
            cost += self._rejoin_cost(node, spec)
        return cost

    def _rejoin_cost(self, node: SceneNode, spec: WindowRepairSpec) -> float:
        farthest = 0.0
        heading_err = 0.0
        for actor in spec.free_actors:
            actual = node.scene[actor]
            target = spec.rejoin_scene[actor]
            farthest = max(farthest, float(np.linalg.norm(actual.p - target.p)))
            heading_err += abs(heading_diff(target.heading, actual.heading))
        scale = max(spec.rejoin_tolerance, EPSILON)
        return self.REJOIN_WEIGHT * (farthest / scale + heading_err)

    def is_resolved(self, node: SceneNode) -> bool:
        return all(trajectory_objective.is_resolved(node) for trajectory_objective in self.values())

    def reached_goal(self, node: SceneNode) -> bool:
        return all(trajectory_objective.reached_goal(node) for trajectory_objective in self.values())

    def update_path_state(self, parent: SceneNode, node: SceneNode) -> None:
        for actor, trajectory_objective in self.items():
            node.goal_distances[actor] = trajectory_objective.updated_goal_distance(parent, node)

    def get_suggested_headings(self, node: SceneNode) -> List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
        actors = self._sampled_actors()
        if not actors:
            return [({}, {})]
        suggested_headings: Dict[ConcreteActor, List[float]] = {}
        heading_changes: Dict[ConcreteActor, List[float]] = {}
        for actor in actors:
            sampled = self._sample_actor_headings(actor, node)
            if sampled is None:
                return []
            heading_changes[actor], suggested_headings[actor] = sampled
        return self.combine_headings(suggested_headings, heading_changes, self.max_children_per_expansion)

    def _sampled_actors(self) -> List[ConcreteActor]:
        actors = list(self.keys())
        spec = self.window_spec
        if spec is None:
            return actors
        return [actor for actor in actors if actor in spec.free_actors]

    def _sample_actor_headings(self, actor: ConcreteActor, node: SceneNode) -> Optional[Tuple[List[float], List[float]]]:
        trajectory_objective = self[actor]
        state = node.scene[actor]
        heading_ranges = self._heading_interval_for(actor, node, trajectory_objective)
        if heading_ranges.empty:
            if trajectory_objective.verbose:
                print(f"WARNING: No kinematic heading range for {actor.name}")
            return None
        colregs_constants = node.maneuver_state_set[Relation(actor, actor)].colregs_constants
        extras = self._heading_extras(node, trajectory_objective, colregs_constants)
        sampled = sample_kinematic_heading_changes(heading_ranges, extras, self.samples_per_interval)
        headings = [rotate_heading(state.heading, change) for change in sampled]
        return sampled, headings

    def _heading_extras(self, node: SceneNode, trajectory_objective: TrajectoryObjective, colregs_constants: COLREGSConstraints) -> List[float]:
        extras = [
            colregs_constants.READILY_APPARENT_HEADING_CHANGE,
            -colregs_constants.READILY_APPARENT_HEADING_CHANGE,
            0.0,
        ]
        for domain in trajectory_objective.maneuvering_domains_for(node):
            extras.append(domain.hold_heading_change)
            extras.append(domain.inbound_heading_change)
        return extras

    def _heading_interval_for(self, actor: ConcreteActor, node: SceneNode, trajectory_objective: TrajectoryObjective) -> Interval:
        """Kinematic step, minus heading changes the COLREGS monitor would reject.

        Give-way vessels may steer any way after the first evasive, so reverse is no
        longer dropped from their action set. Stand-on vessels, and the first give-way
        turn, are still clipped to the monitor's suggested types.
        """
        colregs_constants = node.maneuver_state_set[Relation(actor, actor)].colregs_constants
        heading_ranges = kinematic_heading_change_interval(actor, trajectory_objective.time_step, colregs_constants)
        if heading_ranges.empty or actor not in node.maneuver_suggestions:
            return heading_ranges
        suggested = node.maneuver_suggestions.get_suggested_range_of_heading_change(actor, trajectory_objective.time_step, colregs_constants)
        restricted = heading_ranges & suggested
        if not restricted.empty:
            return Interval(restricted)
        persist_only = heading_ranges & suggested_persist_interval(actor, trajectory_objective.time_step, colregs_constants)
        if persist_only.empty:
            return heading_ranges
        return Interval(persist_only)

    @staticmethod
    def combine_headings(
        headings: Dict[ConcreteActor, List[float]],
        heading_changes: Dict[ConcreteActor, List[float]],
        max_combinations: Optional[int] = None,
    ) -> List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
        if not headings:
            return []
        actors = list(headings.keys())
        lists = [list(zip(headings[a], heading_changes[a])) for a in actors]
        if max_combinations is None:
            return [_heading_combo(actors, combo) for combo in product(*lists)]
        return _sampled_heading_combos(actors, lists, max_combinations)


def suggested_persist_interval(actor: ConcreteActor, time_step: float, colregs_constants: COLREGSConstraints) -> Interval:
    return get_suggested_range_of_heading_change_for_persisting_course(actor.get_max_heading_step(time_step), time_step, colregs_constants)


def _heading_combo(actors: List[ConcreteActor], combo: Tuple) -> Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]:
    entry = {actor: heading for actor, (heading, _) in zip(actors, combo)}
    changes = {actor: change for actor, (_, change) in zip(actors, combo)}
    return entry, changes


def _combo_key(changes: Dict[ConcreteActor, float], actors: List[ConcreteActor]) -> Tuple[float, ...]:
    return tuple(changes[actor] for actor in actors)


def _persist_combo(actors: List[ConcreteActor], lists: List[List[Tuple[float, float]]]) -> Optional[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
    picked = []
    for pairs in lists:
        best = min(pairs, key=lambda pair: abs(pair[1]))
        if abs(best[1]) > 0.1:
            return None
        picked.append(best)
    return _heading_combo(actors, tuple(picked))


def _sampled_heading_combos(
    actors: List[ConcreteActor],
    lists: List[List[Tuple[float, float]]],
    max_combinations: int,
) -> List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]]:
    """Always try persist (hold the current heading), then random legal products."""
    result: List[Tuple[Dict[ConcreteActor, float], Dict[ConcreteActor, float]]] = []
    seen = set()
    persist = _persist_combo(actors, lists)
    if persist is not None:
        result.append(persist)
        seen.add(_combo_key(persist[1], actors))
    attempts = 0
    limit = max(max_combinations * 8, max_combinations)
    while len(result) < max_combinations and attempts < limit:
        attempts += 1
        combo = tuple(random.choice(pairs) for pairs in lists)
        entry = _heading_combo(actors, combo)
        key = _combo_key(entry[1], actors)
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def kinematic_heading_change_interval(actor: ConcreteActor, time_step: float, colregs_constants: COLREGSConstraints) -> Interval:
    """Full kinematic turn, minus the Rule 8 dead zone between persisting and readily apparent."""
    max_heading_step = actor.get_max_heading_step(time_step)
    if max_heading_step <= 0:
        return Interval()
    persist = min(
        colregs_constants.undetectable_heading_change(time_step),
        colregs_constants.UNDETECTABLE_HEADING_CHANGE,
        max_heading_step,
    )
    persist = max(persist - EPSILON, 0.0)
    readily_apparent = colregs_constants.readily_apparent_heading_change(time_step) * READILY_APPARENT_PLANNING_MARGIN + EPSILON
    parts: List[Interval] = []
    if persist > 0:
        parts.append(Interval.closed(-persist, persist))
    if readily_apparent <= max_heading_step:
        parts.append(Interval.closed(readily_apparent, max_heading_step))
        parts.append(Interval.closed(-max_heading_step, -readily_apparent))
    if not parts:
        return Interval()
    return Interval(*parts)


def sample_kinematic_heading_changes(heading_ranges: Interval, extras: List[float], k: int) -> List[float]:
    """Endpoints of every band, plus hold-course and readily apparent angles when they fit."""
    samples: List[float] = []
    for sub in heading_ranges._intervals:
        samples.extend(_sample_subinterval(sub.lower, sub.upper, extras, k))
    return samples


def _sample_subinterval(low: float, high: float, extras: List[float], k: int) -> List[float]:
    if k <= 1 or high - low <= 0:
        return [random.uniform(low, high)]
    chosen = [low, high]
    for extra in extras:
        if len(chosen) >= k:
            break
        if _is_fresh_interior(extra, low, high, chosen):
            chosen.append(extra)
    mid = (low + high) / 2.0
    if len(chosen) < k and _is_fresh_interior(mid, low, high, chosen):
        chosen.append(mid)
    while len(chosen) < k:
        chosen.append(random.uniform(low, high))
    return chosen


def _is_fresh_interior(value: float, low: float, high: float, chosen: List[float]) -> bool:
    if value <= low + EPSILON or value >= high - EPSILON:
        return False
    return all(abs(value - existing) > EPSILON for existing in chosen)


class TrajectoryTreeBuilder:
    def __init__(self, root_scene: ConcreteScene, time_step: int, monitor_set: COLREGSMonitor, root_node: Optional[SceneNode] = None):
        del root_scene
        self._next_node_id = 0
        self.node_list: Dict[int, SceneNode] = {}
        if root_node is None:
            self.root = SceneNode(monitored_scene_with_results=monitor_set.initial_monitored_scene_with_results)
        else:
            self.root = root_node
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
        if not suggested_headings:
            suggested_headings = [({}, {})]
        return [self._steer_one(nearest_node, trajectory_objective_set, headings, heading_changes) for headings, heading_changes in suggested_headings]

    def _steer_one(
        self,
        nearest_node: SceneNode,
        trajectory_objective_set: TrajectoryObjectiveSet,
        headings: Dict[ConcreteActor, float],
        heading_changes: Dict[ConcreteActor, float],
    ) -> SceneNode:
        spec = trajectory_objective_set.window_spec
        next_scene = SceneBuilder(nearest_node.scene)
        changes = dict(heading_changes)
        for actor in nearest_node.scene.vessels:
            change, next_state = self._next_actor_motion(nearest_node, actor, headings, spec)
            next_scene.set_state(actor, next_state)
            changes[actor] = change
        monitored = self.monitor.step(nearest_node.monitored_scene_with_results, next_scene.build(), self.time_step)
        next_node = SceneNode(monitored_scene_with_results=monitored)
        next_node.heading_steps = changes
        next_node.window_depth = nearest_node.window_depth + 1
        if spec is not None and next_node.window_depth >= spec.length:
            next_node.is_dead_end = True
        next_node.inherit_running_extremes(nearest_node)
        trajectory_objective_set.update_path_state(nearest_node, next_node)
        next_node.path_cost = nearest_node.path_cost + trajectory_objective_set.calculate_step_cost(nearest_node, next_node)
        return next_node

    def _next_actor_motion(
        self,
        nearest_node: SceneNode,
        actor: ConcreteActor,
        headings: Dict[ConcreteActor, float],
        spec: Optional[WindowRepairSpec],
    ) -> Tuple[float, ActorState]:
        if spec is not None and actor not in spec.free_actors:
            return spec.locked_heading_change(nearest_node.window_depth, actor), spec.locked_state(nearest_node.window_depth, actor)
        actor_state = nearest_node.scene[actor]
        heading = headings[actor]
        next_state = actor.simulate(actor_state, (heading, actor_state.speed), self.time_step)
        return heading_diff(heading, actor_state.heading), next_state

    def get_best_leafs(self, trajectory_objective: TrajectoryObjective, k: int) -> List[SceneNode]:
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
        nodes = self.expandable_leaves
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]

    def get_best_expandable_nodes_global(self, trajectory_objective_set: TrajectoryObjectiveSet, k: int) -> List[SceneNode]:
        nodes = self.expandable_nodes
        nodes.sort(key=lambda node: trajectory_objective_set.calculate_cost(node))
        return nodes[:k]
