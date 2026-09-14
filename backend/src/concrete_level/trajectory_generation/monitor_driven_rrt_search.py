# pyright: reportMissingImports=false
import random
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredTrajectory
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.seed_trajectory import (
    build_seed_nodes,
    clone_as_root,
    detach_node,
    extend_seed_nodes,
    first_failure_index,
    original_headings_from_root,
    repair_window,
    window_rejoins,
)
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, TrajectoryObjectiveSet, TrajectoryTreeBuilder, WindowRepairSpec
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import EPSILON
from utils.math_utils import calculate_heading, heading_diff, magnitude, rotate_heading


class MonitorDrivenRRTSearch:
    GOAL_SAMPLE_RATE: int = 50
    BEST_LEAF_SAMPLE_RATE: int = 90
    MAX_LEAFS: int = 500
    ANIM_UPDATE_INTERVAL: int = 1
    VERBOSE: bool = True
    SHOW_ANIMATION: bool = True
    DIRECTION_THRESHOLD = 1.0  # meter
    BEST_RANDOM_NODES_K: int = 20
    # Shortcut-and-re-simulate passes over the finished path. Each round applies at most
    # one accepted shortcut, so a few rounds straighten the worst corners without the
    # cost of a full rewiring search.
    SMOOTHING_ROUNDS: int = 6
    # Shortcut candidates tried per round, and the longest stretch one may replace.
    SMOOTHING_ATTEMPTS: int = 24
    MAX_SHORTCUT_SPAN: int = 8
    WINDOW_MAX_ITERATIONS: int = 24
    MAX_REPAIR_ROUNDS: int = 6

    def __init__(
        self,
        start_scene: ConcreteScene,
        other_trajectories: Trajectories,
        colregs_constants: COLREGSConstraints,
        *,
        observer: Optional[Callable[[Trajectories, MonitoredTrajectory, int], None]] = None,
        termination_signal: Optional[Callable[[], bool]] = None,
        max_iterations: Optional[int] = None,
        goal_sample_rate: Optional[int] = None,
        best_leaf_sample_rate: Optional[int] = None,
        max_leafs: Optional[int] = None,
        anim_update_interval: Optional[int] = None,
        direction_threshold: Optional[float] = None,
        best_random_nodes_k: Optional[int] = None,
        verbose: Optional[bool] = None,
        show_animation: Optional[bool] = None,
    ) -> None:
        self.start_scene = start_scene
        self.other_trajectories = other_trajectories
        self.time_step = other_trajectories.time_step
        self.monitor = COLREGSMonitor(self.start_scene, colregs_constants)
        self.trajectory_tree_builder = TrajectoryTreeBuilder(self.start_scene, self.time_step, self.monitor)

        # Optional per-instance overrides for the class-level tuning constants. When a
        # value is left as ``None`` the class attribute is used unchanged (headless
        # subsystem callers pass explicit values; the matplotlib script path does not).
        if goal_sample_rate is not None:
            self.GOAL_SAMPLE_RATE = goal_sample_rate
        if best_leaf_sample_rate is not None:
            self.BEST_LEAF_SAMPLE_RATE = best_leaf_sample_rate
        if max_leafs is not None:
            self.MAX_LEAFS = max_leafs
        if anim_update_interval is not None:
            self.ANIM_UPDATE_INTERVAL = max(1, anim_update_interval)
        if direction_threshold is not None:
            self.DIRECTION_THRESHOLD = direction_threshold
        if best_random_nodes_k is not None:
            self.BEST_RANDOM_NODES_K = best_random_nodes_k
        if verbose is not None:
            self.VERBOSE = verbose
        if show_animation is not None:
            self.SHOW_ANIMATION = show_animation

        self._observer = observer
        self._termination_signal = termination_signal
        self._max_iterations = max_iterations

        # Internal state
        self._iteration_count = 0
        self.stop = False
        self._best_leaf: Optional[SceneNode] = None

        # # Calculate X and Y distances
        # shifted_points_x = [line.shifted_point[0] for line in bounding_lines]
        # shifted_points_y = [line.shifted_point[1] for line in bounding_lines]

        # X_DIST = (min(shifted_points_x), max(shifted_points_x))
        # Y_DIST = (min(shifted_points_y), max(shifted_points_y))
        # self.sample_area = [X_DIST, Y_DIST]

        # other_trajectories is the constant-course baseline for the whole scene, so its
        # timespan is the horizon the planner is expected to cover, and that is what
        # sets how far ahead each vessel's goal sits.
        self.trajectory_objective_set = TrajectoryObjectiveSet(
            self.trajectory_tree_builder.root,
            self.time_step,
            self.GOAL_SAMPLE_RATE,
            self.VERBOSE,
            goal_horizon=float(self.other_trajectories.timespan),
        )

        if self.SHOW_ANIMATION:
            from visualization.trajectory_visualizer import RRTStarVisualizer

            self.trajectory_visualizer = RRTStarVisualizer(
                trajectory_tree_builder=self.trajectory_tree_builder,
                trajectory_objective_set=self.trajectory_objective_set,
            )

    @property
    def iteration_count(self) -> int:
        return self._iteration_count

    def _should_stop(self) -> bool:
        if self.stop:
            return True
        if self._max_iterations is not None and self._iteration_count >= self._max_iterations:
            return True
        if self._termination_signal is not None and self._termination_signal():
            return True
        return False

    def current_best_trajectories(self) -> Optional[Trajectories]:
        last_node = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)
        trajectories, _ = self.trajectory_tree_builder.get_path_trajectories(last_node)
        return trajectories

    def current_best_monitored_trajectory(self) -> Optional[MonitoredTrajectory]:
        """Monitor output along the current best path, scene by scene.

        Every node already carries the monitor result that was computed when it was
        steered, so this is a walk up the tree, not a second monitoring pass.
        """
        last_node = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)
        return self.trajectory_tree_builder.get_monitored_trajectory(last_node)

    def do_plan(self) -> Optional[Trajectories]:
        horizon = float(self.other_trajectories.timespan)
        nodes = build_seed_nodes(
            self.monitor,
            self.time_step,
            horizon,
            should_stop=self._should_stop,
            on_progress=self._on_seed_progress,
        )
        original_headings = original_headings_from_root(nodes[0])
        if self.VERBOSE:
            print(f"Seed path has {len(nodes)} scenes")
        if not self._should_stop():
            nodes = self._repair_until_clean(nodes, original_headings, horizon)
        self._install_path(nodes)
        self._notify_observer()
        return self._trajectories_from_nodes(nodes)

    def _on_seed_progress(self, nodes: List[SceneNode]) -> None:
        self._iteration_count += 1
        if self._observer is None:
            return
        if self._iteration_count % self.ANIM_UPDATE_INTERVAL != 0:
            return
        try:
            self._observer(self._trajectories_from_nodes(nodes), self._monitored_from_nodes(nodes), self._iteration_count)
        except Exception:
            return

    def _monitored_from_nodes(self, nodes: List[SceneNode]) -> MonitoredTrajectory:
        monitored = MonitoredTrajectory(time_step=self.time_step)
        for node in nodes:
            monitored.add_scene(node.monitored_scene_with_results)
        return monitored

    def _repair_until_clean(
        self,
        nodes: List[SceneNode],
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> List[SceneNode]:
        for round_index in range(self.MAX_REPAIR_ROUNDS):
            if self._should_stop():
                return nodes
            failure = first_failure_index(nodes)
            if failure is None:
                if self.VERBOSE:
                    print(f"Seed is COLREGS-clean after {round_index} repair rounds")
                return nodes
            repaired = self._repair_one_failure(nodes, failure, original_headings, horizon)
            if repaired is nodes:
                if self.VERBOSE:
                    print(f"Window repair could not replace the failed seed step at index {failure}")
                return nodes
            nodes = repaired
        return nodes

    def _repair_one_failure(
        self,
        nodes: List[SceneNode],
        failure_index: int,
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> List[SceneNode]:
        spec = repair_window(nodes, failure_index, False, self.DIRECTION_THRESHOLD)
        if spec is None:
            return nodes
        path = self._search_window(spec)
        rejoined = self._splice_if_rejoined(nodes, spec, path, original_headings, horizon)
        if rejoined is not None:
            return rejoined
        wide = repair_window(nodes, failure_index, True, self.DIRECTION_THRESHOLD)
        return self._repair_widened(nodes, spec, path, wide, original_headings, horizon)

    def _repair_widened(
        self,
        nodes: List[SceneNode],
        spec: WindowRepairSpec,
        path: Optional[List[SceneNode]],
        wide: Optional[WindowRepairSpec],
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> List[SceneNode]:
        if not self._wider_window(spec, wide) or wide is None:
            return self._splice_or_keep(nodes, spec, path, original_headings, horizon)
        wide_path = self._search_window(wide)
        rejoined = self._splice_if_rejoined(nodes, wide, wide_path, original_headings, horizon)
        if rejoined is not None:
            return rejoined
        if wide_path is not None:
            return self._splice_extend(nodes, wide, wide_path, original_headings, horizon)
        return self._splice_or_keep(nodes, spec, path, original_headings, horizon)

    def _splice_if_rejoined(
        self,
        nodes: List[SceneNode],
        spec: WindowRepairSpec,
        path: Optional[List[SceneNode]],
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> Optional[List[SceneNode]]:
        if path is None or not window_rejoins(path[-1], spec, self.time_step):
            return None
        return self._splice_extend(nodes, spec, path, original_headings, horizon)

    def _splice_or_keep(
        self,
        nodes: List[SceneNode],
        spec: WindowRepairSpec,
        path: Optional[List[SceneNode]],
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> List[SceneNode]:
        if path is None:
            return nodes
        return self._splice_extend(nodes, spec, path, original_headings, horizon)

    def _wider_window(self, spec: WindowRepairSpec, wide: Optional[WindowRepairSpec]) -> bool:
        if wide is None:
            return False
        return (wide.start, wide.end) != (spec.start, spec.end)

    def _splice_extend(
        self,
        nodes: List[SceneNode],
        spec: WindowRepairSpec,
        window_path: List[SceneNode],
        original_headings: Dict[ConcreteActor, float],
        horizon: float,
    ) -> List[SceneNode]:
        spliced = [detach_node(node) for node in nodes[: spec.start + 1]]
        spliced.extend(detach_node(node) for node in window_path[1:])
        return extend_seed_nodes(spliced, self.monitor, original_headings, self.time_step, horizon, should_stop=self._should_stop)

    def _search_window(self, spec: WindowRepairSpec) -> Optional[List[SceneNode]]:
        tree = TrajectoryTreeBuilder(self.start_scene, self.time_step, self.monitor, root_node=clone_as_root(spec.seed_nodes[spec.start]))
        objectives = TrajectoryObjectiveSet(
            tree.root,
            self.time_step,
            self.GOAL_SAMPLE_RATE,
            False,
            goal_horizon=float(self.other_trajectories.timespan),
        )
        objectives.window_spec = spec
        best_leaf = tree.root
        for _ in range(self.WINDOW_MAX_ITERATIONS):
            if self._should_stop():
                break
            parents = self._window_parents(tree, objectives)
            if not parents:
                break
            for parent in parents:
                if parent.id not in tree.node_list:
                    continue
                self._expand_node(parent, tree, objectives)
            best_leaf = tree.get_best_leaf_global(objectives)
            if window_rejoins(best_leaf, spec, self.time_step):
                return tree.get_path(best_leaf)
        path = tree.get_path(best_leaf)
        if len(path) <= 1:
            return None
        return path

    def _window_parents(self, tree: TrajectoryTreeBuilder, objectives: TrajectoryObjectiveSet) -> List[SceneNode]:
        parents = tree.get_best_expandable_leafs_global(objectives, self.BEST_RANDOM_NODES_K)
        if parents:
            return parents
        return tree.get_best_expandable_nodes_global(objectives, self.BEST_RANDOM_NODES_K)

    def _install_path(self, nodes: List[SceneNode]) -> None:
        for node in nodes:
            detach_node(node)
            node.window_depth = 0
        tree = TrajectoryTreeBuilder(self.start_scene, self.time_step, self.monitor, root_node=nodes[0])
        objectives = TrajectoryObjectiveSet(
            tree.root,
            self.time_step,
            self.GOAL_SAMPLE_RATE,
            self.VERBOSE,
            goal_horizon=float(self.other_trajectories.timespan),
        )
        current = tree.root
        for node in nodes[1:]:
            objectives.update_path_state(current, node)
            node.path_cost = current.path_cost + objectives.calculate_step_cost(current, node)
            tree.add_node(current, node)
            current = node
        self.trajectory_tree_builder = tree
        self.trajectory_objective_set = objectives
        self._best_leaf = current
        if self.SHOW_ANIMATION:
            self.trajectory_visualizer.trajectory_tree_builder = tree
            self.trajectory_visualizer.trajectory_objective_set = objectives

    def _trajectories_from_nodes(self, nodes: List[SceneNode]) -> Trajectories:
        return TrajectoryBuilder(scene_list=[node.scene for node in nodes], time_step=self.time_step).build()

    def _expand_node(self, parent_node: SceneNode, tree: Optional[TrajectoryTreeBuilder] = None, objectives: Optional[TrajectoryObjectiveSet] = None) -> None:
        """Steer one node and attach the successors that survive every admissibility test."""
        tree = self.trajectory_tree_builder if tree is None else tree
        objectives = self.trajectory_objective_set if objectives is None else objectives
        new_nodes = tree.steer_actors(parent_node, objectives)
        self._log_expansion(objectives, f"New nodes: {len(new_nodes)}")
        if len(new_nodes) == 0:
            self._log_expansion(objectives, f"Dead end, no successor could be sampled from node {parent_node.id}")
            parent_node.is_dead_end = True
            return
        if all(new_node.monitor_result_map_set.is_failed() for new_node in new_nodes):
            self._log_failed_nodes(objectives, new_nodes)
            tree.remove_branch_until_parent_with_multiple_children(parent_node)
            return
        if self._attach_successors(parent_node, new_nodes, tree, objectives) == 0:
            parent_node.is_dead_end = True

    def _log_expansion(self, objectives: TrajectoryObjectiveSet, message: str) -> None:
        if self.VERBOSE and objectives.window_spec is None:
            print(message)

    def _log_failed_nodes(self, objectives: TrajectoryObjectiveSet, new_nodes: List[SceneNode]) -> None:
        if not (self.VERBOSE and objectives.window_spec is None):
            return
        for new_node in new_nodes:
            self.print_maneuver_states(new_node)

    def _attach_successors(
        self,
        parent_node: SceneNode,
        new_nodes: List[SceneNode],
        tree: Optional[TrajectoryTreeBuilder] = None,
        objectives: Optional[TrajectoryObjectiveSet] = None,
    ) -> int:
        """Add the successors that the COLREGS monitor accepts. Returns how many."""
        tree = self.trajectory_tree_builder if tree is None else tree
        objectives = self.trajectory_objective_set if objectives is None else objectives
        added = 0
        for new_node in new_nodes:
            if new_node.monitor_result_map_set.is_failed():
                self._log_failed_rules(objectives, new_node)
                continue
            tree.add_node(parent_node, new_node)
            added += 1
            if self.VERBOSE and objectives.window_spec is None:
                self.print_maneuver_states(new_node)
        return added

    def _log_failed_rules(self, objectives: TrajectoryObjectiveSet, new_node: SceneNode) -> None:
        if not (self.VERBOSE and objectives.window_spec is None):
            return
        for rel, rules in new_node.monitor_result_map_set.get_failed_rules().items():
            print(f"Failed in {rel} context: {rules}")

    def _goal_reached(self) -> bool:
        """True once the best leaf has resolved every encounter and reached its goal.

        Before this the search had no goal test at all: it ran until the iteration cap
        or the timeout and returned whatever leaf was cheapest, and the goal itself was
        pushed further out every iteration so it could never be reached.
        """
        best_node = self._best_leaf
        if best_node is None or best_node.id not in self.trajectory_tree_builder.node_list:
            return False
        if not self.trajectory_objective_set.is_resolved(best_node):
            return False
        return self.trajectory_objective_set.reached_goal(best_node)

    def smooth_path(self, last_node: SceneNode) -> Trajectories:
        """Replace corner sequences on the final path with re-simulated shortcuts.

        Rewiring the tree in place is not sound here: a node's COLREGS state is produced
        by stepping the monitor from its parent, so re-parenting a node would invalidate
        its own monitor state and every descendant's. Instead the finished path is
        smoothed as a post-process and each candidate is re-run through the monitor from
        the branch point, so a shortcut is only accepted when it is still compliant and
        actually cheaper.
        """
        node_path = self.trajectory_tree_builder.get_path(last_node)
        if len(node_path) < 3:
            return self.trajectory_tree_builder.get_path_trajectories(last_node)[0]

        best_path = node_path
        best_cost = self.trajectory_objective_set.calculate_cost(best_path[-1])

        for _ in range(self.SMOOTHING_ROUNDS):
            improved = False
            # Sampled rather than exhaustive: every attempt re-simulates the rest of the
            # path through the monitor, so trying all (start, span) pairs would be cubic
            # in the path length and dominate the whole planner.
            for _attempt in range(self.SMOOTHING_ATTEMPTS):
                if len(best_path) < 3:
                    break
                span = random.randint(2, min(self.MAX_SHORTCUT_SPAN, len(best_path) - 1))
                start = random.randint(0, len(best_path) - 1 - span)
                candidate = self._try_shortcut(best_path, start, start + span)
                if candidate is None:
                    continue
                candidate_cost = self.trajectory_objective_set.calculate_cost(candidate[-1])
                if candidate_cost < best_cost:
                    best_path, best_cost = candidate, candidate_cost
                    improved = True
                    break
            if not improved:
                break

        builder = TrajectoryBuilder(scene_list=[node.scene for node in best_path], time_step=self.time_step)
        return builder.build()

    def _try_shortcut(self, node_path: List[SceneNode], start_index: int, end_index: int) -> Optional[List[SceneNode]]:
        """Re-steer directly from node_path[start_index] toward node_path[end_index].

        Returns the rebuilt path if every re-simulated scene still passes the monitor,
        otherwise None. The tail beyond end_index is re-simulated too, since its monitor
        state depends on everything before it.
        """
        start_node = node_path[start_index]
        target_scene = node_path[end_index].scene
        steps = end_index - start_index

        rebuilt: List[SceneNode] = list(node_path[: start_index + 1])
        current = start_node
        for step in range(steps):
            remaining = steps - step
            next_scene_builder = SceneBuilder(current.scene)
            heading_steps: Dict[ConcreteActor, float] = {}
            for actor in current.scene.vessels:
                state = current.scene[actor]
                # Aim straight at where this actor has to be at the end of the shortcut,
                # spreading the remaining correction over the remaining steps.
                to_target = target_scene[actor].p - state.p
                heading_ref = calculate_heading(to_target) if magnitude(to_target) > EPSILON else state.heading
                max_step = actor.get_max_heading_step(self.time_step)
                desired = heading_diff(heading_ref, state.heading) / remaining
                heading_step = float(np.clip(desired, -max_step, max_step))
                heading_steps[actor] = heading_step
                next_scene_builder.set_state(actor, actor.simulate(state, (rotate_heading(state.heading, heading_step), state.speed), self.time_step))

            monitored = self.monitor.step(current.monitored_scene_with_results, next_scene_builder.build(), self.time_step)
            if monitored.monitor_result_map_set.is_failed():
                return None

            candidate_node = SceneNode(monitored_scene_with_results=monitored)
            candidate_node.heading_steps = heading_steps
            candidate_node.inherit_running_extremes(current)
            self.trajectory_objective_set.update_path_state(current, candidate_node)
            candidate_node.path_cost = current.path_cost + self.trajectory_objective_set.calculate_step_cost(current, candidate_node)
            rebuilt.append(candidate_node)
            current = candidate_node

        # Re-simulate the untouched tail so its monitor state matches the new prefix.
        for tail_node in node_path[end_index + 1 :]:
            next_scene_builder = SceneBuilder(current.scene)
            heading_steps = {}
            for actor in current.scene.vessels:
                state = current.scene[actor]
                heading_step = heading_diff(tail_node.scene[actor].heading, state.heading)
                max_step = actor.get_max_heading_step(self.time_step)
                heading_step = float(np.clip(heading_step, -max_step, max_step))
                heading_steps[actor] = heading_step
                next_scene_builder.set_state(actor, actor.simulate(state, (rotate_heading(state.heading, heading_step), state.speed), self.time_step))

            monitored = self.monitor.step(current.monitored_scene_with_results, next_scene_builder.build(), self.time_step)
            if monitored.monitor_result_map_set.is_failed():
                return None
            candidate_node = SceneNode(monitored_scene_with_results=monitored)
            candidate_node.heading_steps = heading_steps
            candidate_node.inherit_running_extremes(current)
            self.trajectory_objective_set.update_path_state(current, candidate_node)
            candidate_node.path_cost = current.path_cost + self.trajectory_objective_set.calculate_step_cost(current, candidate_node)
            rebuilt.append(candidate_node)
            current = candidate_node

        return rebuilt

    def print_maneuver_states(self, node: SceneNode) -> None:
        for relation, maneuver_state in node.maneuver_state_set.items():
            print("------------------------------------------------------------------------------------------------")
            print(f"Actor: {relation.actor1.name}")
            print(f"Node index: {node.id}")
            print(f"Failed rules: {node.monitor_result_map_set.get_failed_rules()}")
            print(f"Current maneuver: {maneuver_state}")
            print(f"Heading change since start: {maneuver_state.heading_change.heading_diff_since_start_deg}")
            print(f"Heading change since readily apparent time: {maneuver_state.heading_change.heading_diff_since_readily_apparent_time_deg}")
            print(f"Readily apparent timestamp: {maneuver_state.readily_apparent_timestamp}")
            print("------------------------------------------------------------------------------------------------")

    def end_iteration(self) -> None:
        if self.SHOW_ANIMATION:
            self.update_anim()

        if len(self.trajectory_tree_builder.leaves) > self.MAX_LEAFS:
            self.trajectory_tree_builder.prune_worst_leaves_global(self.trajectory_objective_set, self.MAX_LEAFS // 10)

        # Sorting every leaf by cost is the most expensive thing per iteration, so the
        # winner is computed once here and reused by the goal test and the observer.
        self._best_leaf = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)

        self._iteration_count += 1
        self._notify_observer()

    def _notify_observer(self) -> None:
        if self._observer is None:
            return
        if self._iteration_count % self.ANIM_UPDATE_INTERVAL != 0:
            return
        try:
            last_node = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)
            best, _ = self.trajectory_tree_builder.get_path_trajectories(last_node)
            monitored = self.trajectory_tree_builder.get_monitored_trajectory(last_node)
        except Exception:
            return
        if best is not None:
            self._observer(best, monitored, self._iteration_count)

    def update_anim(self) -> None:
        if self._iteration_count % self.ANIM_UPDATE_INTERVAL == 0:
            self.trajectory_visualizer.update(self._iteration_count)
        if self.trajectory_visualizer.handle_user_input():
            self.stop = True

    def plan_trajectory(self) -> Tuple[Trajectories, int]:
        """Plan a trajectory and return the path from start to goal.

        Returns the path as a list of `RRTNode` from start to goal.
        Raises an exception if no path can be found.
        """
        path = self.do_plan()
        if path is None:
            raise Exception("No path is found")
        return path, self._iteration_count

    # def path_validation(self, goal_position: np.ndarray) -> None:
    #     last_node_opt = self.trajectory_tree_builder.get_goal_node(goal_position)
    #     if last_node_opt is None:
    #         return
    #     current_node = last_node_opt
    #     while True:
    #         parent = self.trajectory_tree_builder.parent(current_node)
    #         if parent is None:
    #             break
    #         ok, _ = self.check_no_collision_extend(self.node_list[parent_index], self.node_list[current_index])
    #         if not ok:
    #             self.trajectory_tree_builder.remove_branch(current_node)
    #         current_node = parent

    # def choose_parent(self) -> SceneNode:
    #     branch = self.trajectory_tree_builder.get_best_random_node(point=self.goal_position, k=self.BEST_RANDOM_NODE_K)
    #     random_leaf = self.trajectory_tree_builder.random_leaf
    #     return random_leaf
    #     if random.randint(0, 100) > self.LEAF_SAMPLE_RATE:
    #         random_node = self.trajectory_tree_builder.random_node_on_path(branch)
    #         return self.trajectory_tree_builder.find_previous_actor_maneuver(random_node)
    #     return branch

    # def choose_parent(self, new_node: SceneNode, nearest_indexes: Iterable[int]) -> bool:
    #     indexes = list(nearest_indexes)
    #     if len(indexes) == 0:
    #         return False

    #     min_cost = float("inf")
    #     min_cost_index: Optional[int] = None
    #     for i in indexes:
    #         no_coll, dist = self.check_no_collision_extend(self.node_list[i], new_node)
    #         if no_coll:
    #             cost = self.node_list[i].distance_cost + dist
    #             if cost < min_cost:
    #                 min_cost = cost
    #                 min_cost_index = i

    #     if min_cost_index is None:
    #         if self.DEBUG_OUTPUT:
    #             print("No feasible parent found for new node.")
    #         return False

    #     new_node.distance_cost = min_cost
    #     new_node.parent = min_cost_index
    #     return True

    # def get_random_point(self) -> np.ndarray:
    #     if random.randint(0, 100) < self.GOAL_SAMPLE_RATE:
    #         return self.goal_position
    #     return np.array([random.uniform(*self.sample_area[0]), random.uniform(*self.sample_area[1])])

    # def find_valid_parents(self, random_point: np.ndarray) -> List[SceneNode]:
    #     valid_parents: List[SceneNode] = []
    #     for node in self.trajectory_tree_builder.node_list.values():
    #         heading_diff_to_point = heading_diff(node.scene[self.vessel].heading, calculate_heading(random_point - node.scene[self.vessel].p))
    #         suggested_maneuvers = node.maneuver_suggestions
    #         suggested_ranges = suggested_maneuvers.get_suggested_range_of_heading_change(self.vessel, self.time_step)
    #         if suggested_ranges.contains(heading_diff_to_point):
    #             valid_parents.append(node)
    #     return valid_parents

    # def find_best_parent(self, valid_parents: List[SceneNode], random_point: np.ndarray) -> Optional[SceneNode]:
    #     min_cost = float("inf")
    #     best_node: Optional[SceneNode] = None
    #     for node in valid_parents:
    #         cost = distance(node.scene[self.vessel].p, random_point)
    #         if cost < min_cost:
    #             min_cost = cost
    #             best_node = node
    #     return best_node

    # def get_random_headings(self, nearest_node: SceneNode, max_headings: int = 10) -> List[float]:
    #     actor_state = nearest_node.scene[self.vessel]
    #     choice = self.get_heading_sample_choice()

    #     suggested_maneuvers = nearest_node.maneuver_suggestions
    #     print(f"Suggested maneuvers: {suggested_maneuvers}")
    #     # Get the suggested range of heading change for the chosen maneuvers
    #     suggested_ranges = suggested_maneuvers.get_suggested_range_of_heading_change(self.vessel, self.time_step)

    #     self.actor_state = actor_state.modify_copy(heading=suggested_ranges.sample())

    #     if suggested_ranges.empty:
    #         raise ValueError("No suggested ranges found")

    #     # if (current_maneuver_type := nearest_node.maneuver_state_set[self.relation].type) in vessel_maneuvers and random.randint(0, 100) < self.STAY_IN_CURRENT_MANEUVER_RATE:
    #     #     vessel_maneuvers = {current_maneuver_type}

    #     headings = [rotate_heading(actor_state.heading, random.uniform(suggested_range[0], suggested_range[1])) for suggested_range in suggested_ranges]

    #     return random.sample(headings, min(max_headings, len(headings)))

    #     if choice == HeadingSampleChoices.GOAL_DIRECTION:
    #         heading_to_goal = calculate_heading(self.goal_position - actor_state.p)
    #         headings.append(self.vessel.sample_random_heading(actor_state, heading_to_goal, self.time_step))
    #     elif choice == HeadingSampleChoices.ORIGINAL_HEADING:
    #         headings.append(self.vessel.sample_random_heading(actor_state, self.start_state.heading, self.time_step))

    # def rewire(self, new_node_index: int, new_node: RRTNode, near_indexes: Iterable[int]) -> None:
    #     for i in near_indexes:
    #         near_node = self.node_list[i]

    #         d = distance(new_node.p, near_node.p)
    #         new_cost = new_node.distance_cost + d

    #         if near_node.distance_cost > new_cost:
    #             no_coll, _ = self.check_no_collision_extend(new_node, near_node)
    #             if no_coll:
    #                 if near_node.parent is not None:
    #                     self.node_list[near_node.parent].children.discard(i)
    #                 near_node.parent = new_node_index
    #                 s_d, s_fraction = RRTNode.calc_cost(self.start_scene, d)
    #                 near_node.set_cost(new_cost, s_d + new_node.cost, s_fraction)
    #                 new_node.children.add(i)

    # def check_no_collision_extend(self, parent_node: SceneNode, node: SceneNode) -> Tuple[bool, float]:
    #     delta_pos = node.scene[self.vessel].p - parent_node.scene[self.vessel].p
    #     dist = magnitude(delta_pos)

    #     tmp_node = RRTNode(np.array([parent_node.p[0], parent_node.p[1]]))
    #     s_d, s_fraction = RRTNode.calc_cost(self.start_scene, dist)
    #     s_d = int(s_d - int(np.ceil(s_fraction)))

    #     if s_d <= 0:
    #         return self.check_no_collision(node, self.obstacle_list), dist

    #     for s in range(s_d):
    #         fraction = s / s_d if s_d > 0 else 1.0
    #         tmp_node.p = parent_node.p + delta_pos * fraction
    #         tmp_node.set_cost(0, parent_node.distance_made + s, 0.0)
    #         if not self.check_no_collision(tmp_node, self.obstacle_list):
    #             return False, dist
    #     return True, dist
