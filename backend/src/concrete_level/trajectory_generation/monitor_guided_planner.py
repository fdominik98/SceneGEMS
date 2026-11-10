# pyright: reportMissingImports=false
from typing import Callable, Dict, List, Optional, Tuple

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredTrajectory
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
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


class MonitorGuidedPlanner:
    """Plans the vessels' trajectories over the whole horizon at once, offline.

    The seed follows each give-way vessel's maneuvering corridor step by step. Where the
    COLREGS monitor fails a seed step, a best-first tree search over a short window
    around it expands the cheapest leaves with sampled heading changes, keeps only the
    children the monitor accepts and splices the stretch back in once it rejoins the
    seed. It samples no random states and does no rewiring, so it is not an RRT.
    """

    ANIM_UPDATE_INTERVAL: int = 1  # seed steps between two observer previews
    VERBOSE: bool = True
    DIRECTION_THRESHOLD = 1.0  # meter: how close a repaired stretch must come to the seed to rejoin it
    BEST_RANDOM_NODES_K: int = 20  # cheapest leaves expanded per window search round
    WINDOW_MAX_ITERATIONS: int = 24
    MAX_REPAIR_ROUNDS: int = 6

    def __init__(
        self,
        start_scene: ConcreteScene,
        other_trajectories: Trajectories,
        colregs_constants: COLREGSConstraints,
        *,
        observer: Optional[Callable[[Trajectories, MonitoredTrajectory, int], Optional[bool]]] = None,
        termination_signal: Optional[Callable[[], bool]] = None,
        max_iterations: Optional[int] = None,
        anim_update_interval: Optional[int] = None,
        direction_threshold: Optional[float] = None,
        best_random_nodes_k: Optional[int] = None,
        verbose: Optional[bool] = None,
    ) -> None:
        self.start_scene = start_scene
        self.other_trajectories = other_trajectories
        self.time_step = other_trajectories.time_step
        # The start scene is given, not planned: a rule it already fails (a pair inside its
        # safe distance) would stick to every node and prune the whole tree.
        self.monitor = COLREGSMonitor(self.start_scene, colregs_constants, judge_initial_scene=False)
        self.trajectory_tree_builder = TrajectoryTreeBuilder(self.start_scene, self.time_step, self.monitor)

        # Optional per-instance overrides for the class-level tuning constants. When a
        # value is left as ``None`` the class attribute is used unchanged (headless
        # subsystem callers pass explicit values; the research script path does not).
        if anim_update_interval is not None:
            self.ANIM_UPDATE_INTERVAL = max(1, anim_update_interval)
        if direction_threshold is not None:
            self.DIRECTION_THRESHOLD = direction_threshold
        if best_random_nodes_k is not None:
            self.BEST_RANDOM_NODES_K = best_random_nodes_k
        if verbose is not None:
            self.VERBOSE = verbose

        self._observer = observer
        self._termination_signal = termination_signal
        self._max_iterations = max_iterations

        # Internal state
        self._iteration_count = 0
        self.stop = False
        self._best_leaf: Optional[SceneNode] = None
        # Index of the first scene of the planned path that still fails a COLREGS rule, None
        # for a clean plan (and before planning). A path is returned either way.
        self.first_failed_step: Optional[int] = None

        # other_trajectories is the constant-course baseline for the whole scene, so its
        # timespan is the horizon the planner is expected to cover, and that is what
        # sets how far ahead each vessel's goal sits.
        self.trajectory_objective_set = TrajectoryObjectiveSet(
            self.trajectory_tree_builder.root,
            self.time_step,
            self.VERBOSE,
            goal_horizon=float(self.other_trajectories.timespan),
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
        self.first_failed_step = first_failure_index(nodes)
        self._notify_observer()
        return self._trajectories_from_nodes(nodes)

    def _on_seed_progress(self, nodes: List[SceneNode]) -> None:
        self._iteration_count += 1
        if self._observer is None:
            return
        if self._iteration_count % self.ANIM_UPDATE_INTERVAL != 0:
            return
        self._preview(nodes)

    def _preview(self, nodes: List[SceneNode]) -> bool:
        """Show the observer the path as it stands. False when the observer did not take it.

        The repair calls this too: a window search can take a minute while the seed before
        it takes a fraction of a second, and without a preview from the repair an observer
        that drops previews arriving too fast was left with the first seed step. Such an
        observer returns False for a preview it dropped, so the caller can offer it again.
        """
        if self._observer is None:
            return True
        try:
            return self._observer(self._trajectories_from_nodes(nodes), self._monitored_from_nodes(nodes), self._iteration_count) is not False
        except Exception:
            return True

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
            self._preview(nodes)
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
            False,
            goal_horizon=float(self.other_trajectories.timespan),
        )
        objectives.window_spec = spec
        best_leaf = tree.root
        # The path under repair is shown once per search: offered each round until the
        # observer takes it, since it may still be dropping previews right after the seed.
        shown = False
        for _ in range(self.WINDOW_MAX_ITERATIONS):
            if self._should_stop():
                break
            shown = shown or self._preview(spec.seed_nodes)
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

    def plan_trajectory(self) -> Tuple[Trajectories, int]:
        """Plan the trajectories over the whole horizon.

        Returns the planned trajectories and the number of seed steps taken.
        Raises an exception if no path can be found.
        """
        path = self.do_plan()
        if path is None:
            raise Exception("No path is found")
        return path, self._iteration_count
