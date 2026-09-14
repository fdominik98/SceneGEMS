from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.colregs_monitoring.situation_context import COLREGSType, SituationContext
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.trajectory_generation.maneuvering_domain import ManeuveringDomain
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, WindowRepairSpec, kinematic_heading_change_interval
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON
from utils.math_utils import calculate_heading, heading_diff, rotate_heading

PHASE_BEFORE = "before"
PHASE_OUTBOUND = "outbound"
PHASE_PARALLEL = "parallel"
PHASE_INBOUND = "inbound"
PHASE_AFTER = "after"
PHASE_ORDER = (PHASE_OUTBOUND, PHASE_PARALLEL, PHASE_INBOUND, PHASE_AFTER)
PHASE_PAD_STEPS = 1
SEED_SETTLE_STEPS = 3
MAX_WINDOW_STEPS = 8


class LatchedGiveWayStore:
    """First give-way context per relation, kept after the pair reverts to OTHER."""

    def __init__(self) -> None:
        self._contexts: Dict[ConcreteActor, Dict[Relation, SituationContext]] = {}
        self._cached_domains: Optional[Dict[ConcreteActor, ManeuveringDomain]] = None

    def update(self, monitored: MonitoredSceneWithResults) -> None:
        for relation, context in monitored.situation_context_set.items():
            if context.situation_type is COLREGSType.OTHER:
                continue
            for actor in context.actors:
                if not context.is_give_way_actor(actor):
                    continue
                per_actor = self._contexts.setdefault(actor, {})
                if relation not in per_actor:
                    per_actor[relation] = context
                    self._cached_domains = None

    def domains(self) -> Dict[ConcreteActor, ManeuveringDomain]:
        if self._cached_domains is None:
            self._cached_domains = self._compute_domains()
        return self._cached_domains

    def _compute_domains(self) -> Dict[ConcreteActor, ManeuveringDomain]:
        domains: Dict[ConcreteActor, ManeuveringDomain] = {}
        for actor, by_relation in self._contexts.items():
            domain = ManeuveringDomain.for_give_way_ship(actor, list(by_relation.values()))
            if domain is not None:
                domains[actor] = domain
        return domains


def latched_domains_from_nodes(nodes: Sequence[SceneNode]) -> Dict[ConcreteActor, ManeuveringDomain]:
    store = LatchedGiveWayStore()
    for node in nodes:
        store.update(node.monitored_scene_with_results)
    return store.domains()


def domains_from_monitored(monitored: MonitoredSceneWithResults) -> Dict[ConcreteActor, ManeuveringDomain]:
    store = LatchedGiveWayStore()
    store.update(monitored)
    return store.domains()


def phase_of_pose(domain: Optional[ManeuveringDomain], along: float, across: float) -> str:
    if domain is None or along < domain.t0 - EPSILON:
        return PHASE_BEFORE
    if along < domain.along_c - EPSILON and not domain.near_outer(across):
        return PHASE_OUTBOUND
    if along < domain.along_c - EPSILON:
        return PHASE_PARALLEL
    if not domain.near_track(across):
        return PHASE_INBOUND
    return PHASE_AFTER


def phase_of_actor(actor: ConcreteActor, node: SceneNode, domain: Optional[ManeuveringDomain]) -> str:
    if domain is None:
        return PHASE_BEFORE
    along, across = domain.local(node.scene[actor].p)
    return phase_of_pose(domain, along, across)


def next_phase(phase: str) -> str:
    if phase == PHASE_BEFORE:
        return PHASE_OUTBOUND
    if phase not in PHASE_ORDER:
        return PHASE_AFTER
    index = PHASE_ORDER.index(phase)
    return PHASE_ORDER[min(index + 1, len(PHASE_ORDER) - 1)]


def seed_desired_heading(state: ActorState, domain: Optional[ManeuveringDomain], original_heading: float) -> float:
    if domain is None:
        return original_heading
    along, across = domain.local(state.p)
    phase = phase_of_pose(domain, along, across)
    if phase == PHASE_OUTBOUND:
        return float(calculate_heading(domain.vertex_b - domain.vertex_a))
    if phase == PHASE_INBOUND:
        return float(calculate_heading(domain.vertex_d - domain.vertex_c))
    return original_heading


def clipped_heading(actor: ConcreteActor, state: ActorState, desired: float, time_step: int, colregs_constants: COLREGSConstraints) -> float:
    delta = heading_diff(desired, state.heading)
    max_step = actor.get_max_heading_step(time_step)
    delta = float(np.clip(delta, -max_step, max_step))
    legal = kinematic_heading_change_interval(actor, time_step, colregs_constants)
    if legal.empty:
        return state.heading
    return rotate_heading(state.heading, legal.crop(delta))


def follow_step(
    scene: ConcreteScene,
    domains: Dict[ConcreteActor, ManeuveringDomain],
    original_headings: Dict[ConcreteActor, float],
    time_step: int,
    colregs_constants: COLREGSConstraints,
) -> Tuple[ConcreteScene, Dict[ConcreteActor, float]]:
    builder = SceneBuilder(scene)
    changes: Dict[ConcreteActor, float] = {}
    for actor in scene.vessels:
        state = scene[actor]
        desired = seed_desired_heading(state, domains.get(actor), original_headings[actor])
        heading = clipped_heading(actor, state, desired, time_step, colregs_constants)
        changes[actor] = heading_diff(heading, state.heading)
        builder.set_state(actor, actor.simulate(state, (heading, state.speed), time_step))
    return builder.build(), changes


def build_seed_nodes(
    monitor: COLREGSMonitor,
    time_step: int,
    horizon: float,
    should_stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[List[SceneNode]], None]] = None,
) -> List[SceneNode]:
    root = SceneNode(monitored_scene_with_results=monitor.initial_monitored_scene_with_results)
    root.heading_steps = {actor: 0.0 for actor in root.scene.vessels}
    original_headings = original_headings_from_root(root)
    nodes = [root]
    latched = LatchedGiveWayStore()
    current = root
    while current.monitored_scene_with_results.timestamp < horizon:
        if should_stop is not None and should_stop():
            break
        current = _append_seed_step(nodes, current, monitor, original_headings, time_step, latched)
        if on_progress is not None:
            on_progress(nodes)
        if seed_maneuver_finished(nodes, latched):
            break
    return nodes


def extend_seed_nodes(
    nodes: List[SceneNode],
    monitor: COLREGSMonitor,
    original_headings: Dict[ConcreteActor, float],
    time_step: int,
    horizon: float,
    should_stop: Optional[Callable[[], bool]] = None,
) -> List[SceneNode]:
    latched = LatchedGiveWayStore()
    for node in nodes:
        latched.update(node.monitored_scene_with_results)
    current = nodes[-1]
    while current.monitored_scene_with_results.timestamp < horizon:
        if should_stop is not None and should_stop():
            break
        current = _append_seed_step(nodes, current, monitor, original_headings, time_step, latched)
        if seed_maneuver_finished(nodes, latched):
            break
    return nodes


def _append_seed_step(
    nodes: List[SceneNode],
    current: SceneNode,
    monitor: COLREGSMonitor,
    original_headings: Dict[ConcreteActor, float],
    time_step: int,
    latched: LatchedGiveWayStore,
) -> SceneNode:
    latched.update(current.monitored_scene_with_results)
    next_scene, changes = follow_step(current.scene, latched.domains(), original_headings, time_step, monitor.colregs_constants)
    monitored = monitor.step(current.monitored_scene_with_results, next_scene, time_step)
    node = SceneNode(monitored_scene_with_results=monitored)
    node.heading_steps = changes
    node.inherit_running_extremes(current)
    nodes.append(node)
    return node


def seed_maneuver_finished(nodes: Sequence[SceneNode], latched: LatchedGiveWayStore) -> bool:
    domains = latched.domains()
    if not domains or len(nodes) < SEED_SETTLE_STEPS + 1:
        return False
    for node in nodes[-SEED_SETTLE_STEPS:]:
        if not _nodes_past_d(node, domains):
            return False
    return True


def _nodes_past_d(node: SceneNode, domains: Dict[ConcreteActor, ManeuveringDomain]) -> bool:
    for actor, domain in domains.items():
        along, across = domain.local(node.scene[actor].p)
        if not domain.reached_d(along, across):
            return False
    return True


def first_failure_index(nodes: Sequence[SceneNode]) -> Optional[int]:
    for index, node in enumerate(nodes):
        if index == 0:
            continue
        if node.monitor_result_map_set.is_failed():
            return index
    return None


def failure_give_way_actors(node: SceneNode) -> Set[ConcreteActor]:
    free: Set[ConcreteActor] = set()
    for relation, rules in node.monitor_result_map_set.get_failed_rules().items():
        if not rules:
            continue
        context = node.monitored_scene_with_results.situation_context_set.get(relation)
        if context is None:
            continue
        for actor in context.actors:
            if context.is_give_way_actor(actor):
                free.add(actor)
    if free:
        return free
    return _all_give_way_actors(node)


def _all_give_way_actors(node: SceneNode) -> Set[ConcreteActor]:
    free: Set[ConcreteActor] = set()
    for context in node.monitored_scene_with_results.situation_context_set.values():
        if context.situation_type is COLREGSType.OTHER:
            continue
        for actor in context.actors:
            if context.is_give_way_actor(actor):
                free.add(actor)
    return free


def repair_window(
    nodes: List[SceneNode],
    failure_index: int,
    extra_phase: bool,
    rejoin_tolerance: float,
) -> Optional[WindowRepairSpec]:
    if failure_index <= 0 or failure_index >= len(nodes):
        return None
    free_actors = failure_give_way_actors(nodes[failure_index])
    if not free_actors:
        return None
    start, end = _repair_span(nodes, failure_index, free_actors, extra_phase)
    return WindowRepairSpec(
        seed_nodes=nodes,
        start=start,
        end=end,
        free_actors=free_actors,
        rejoin_scene=nodes[end].scene,
        rejoin_tolerance=rejoin_tolerance,
    )


def _repair_span(
    nodes: List[SceneNode],
    failure_index: int,
    free_actors: Set[ConcreteActor],
    extra_phase: bool,
) -> Tuple[int, int]:
    parent = nodes[failure_index - 1]
    domains = latched_domains_from_nodes(nodes[:failure_index])
    starts: List[int] = []
    ends: List[int] = []
    for actor in free_actors:
        bounds = _actor_phase_bounds(nodes, parent, actor, domains.get(actor), extra_phase)
        if bounds is not None:
            starts.append(bounds[0])
            ends.append(bounds[1])
    if starts:
        start, end = min(starts), max(ends)
    else:
        start = max(0, failure_index - 1 - PHASE_PAD_STEPS)
        end = min(len(nodes) - 1, failure_index + PHASE_PAD_STEPS)
    start = min(start, max(0, failure_index - 1))
    end = max(end, min(len(nodes) - 1, failure_index))
    if end <= start:
        end = min(len(nodes) - 1, start + 1)
    return _clamp_window(start, end, failure_index, len(nodes))


def _clamp_window(start: int, end: int, failure_index: int, node_count: int) -> Tuple[int, int]:
    if end - start <= MAX_WINDOW_STEPS:
        return start, end
    start = max(0, failure_index - 1 - PHASE_PAD_STEPS)
    end = min(node_count - 1, start + MAX_WINDOW_STEPS)
    if end <= start:
        end = min(node_count - 1, start + 1)
    return start, end


def _actor_phase_bounds(
    nodes: List[SceneNode],
    parent: SceneNode,
    actor: ConcreteActor,
    domain: Optional[ManeuveringDomain],
    extra_phase: bool,
) -> Optional[Tuple[int, int]]:
    phase = phase_of_actor(actor, parent, domain)
    phases = {phase, next_phase(phase)} if extra_phase else {phase}
    return _phase_bounds(nodes, actor, domain, phases)


def _phase_bounds(
    nodes: List[SceneNode],
    actor: ConcreteActor,
    domain: Optional[ManeuveringDomain],
    phases: Set[str],
) -> Optional[Tuple[int, int]]:
    hits = [index for index, node in enumerate(nodes) if phase_of_actor(actor, node, domain) in phases]
    if not hits:
        return None
    start = max(0, min(hits) - PHASE_PAD_STEPS)
    end = min(len(nodes) - 1, max(hits) + PHASE_PAD_STEPS)
    return start, end


def original_headings_from_root(root: SceneNode) -> Dict[ConcreteActor, float]:
    return {actor: root.scene[actor].heading for actor in root.scene.vessels}


def clone_as_root(node: SceneNode) -> SceneNode:
    clone = SceneNode(monitored_scene_with_results=node.monitored_scene_with_results)
    clone.heading_steps = dict(node.heading_steps)
    clone.path_cost = 0.0
    clone.goal_distances = dict(node.goal_distances)
    clone.encountered = set(node.encountered)
    clone.window_depth = 0
    return clone


def detach_node(node: SceneNode) -> SceneNode:
    node.id = -1
    node.parent = None
    node.children = set()
    node.is_dead_end = False
    return node


def window_rejoins(node: SceneNode, spec: WindowRepairSpec, time_step: int) -> bool:
    if node.window_depth < spec.length:
        return False
    for actor in spec.free_actors:
        actual = node.scene[actor]
        target = spec.rejoin_scene[actor]
        if float(np.linalg.norm(actual.p - target.p)) > spec.rejoin_tolerance:
            return False
        if abs(heading_diff(target.heading, actual.heading)) > actor.get_max_heading_step(time_step) + EPSILON:
            return False
    return True
