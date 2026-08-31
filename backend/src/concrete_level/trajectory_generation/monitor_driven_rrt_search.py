# pyright: reportMissingImports=false
import random
from time import sleep
from typing import Callable, Optional, Tuple

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_tree_builder import SceneNode, TrajectoryObjectiveSet, TrajectoryTreeBuilder
from utils.colregs_approximations import COLREGSConstraints


class MonitorDrivenRRTSearch:
    GOAL_SAMPLE_RATE: int = 50
    BEST_LEAF_SAMPLE_RATE: int = 90
    MAX_LEAFS: int = 500
    ANIM_UPDATE_INTERVAL: int = 1
    VERBOSE: bool = True
    SHOW_ANIMATION: bool = True
    DIRECTION_THRESHOLD = 1.0  # meter
    BEST_RANDOM_NODES_K: int = 20

    def __init__(
        self,
        start_scene: ConcreteScene,
        other_trajectories: Trajectories,
        colregs_constants: COLREGSConstraints,
        *,
        observer: Optional[Callable[[Trajectories, int], None]] = None,
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

        # # Calculate X and Y distances
        # shifted_points_x = [line.shifted_point[0] for line in bounding_lines]
        # shifted_points_y = [line.shifted_point[1] for line in bounding_lines]

        # X_DIST = (min(shifted_points_x), max(shifted_points_x))
        # Y_DIST = (min(shifted_points_y), max(shifted_points_y))
        # self.sample_area = [X_DIST, Y_DIST]

        self.trajectory_objective_set = TrajectoryObjectiveSet(self.trajectory_tree_builder.root, self.time_step, self.GOAL_SAMPLE_RATE, self.VERBOSE)

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

    def do_plan(self) -> Optional[Trajectories]:
        while not self._should_stop():
            if self.VERBOSE and self._iteration_count % 100 == 0:
                print(self._iteration_count)

            if random.randint(0, 100) < self.BEST_LEAF_SAMPLE_RATE:
                best_nodes = self.trajectory_tree_builder.get_best_leafs_global(self.trajectory_objective_set, self.BEST_RANDOM_NODES_K)
            else:
                best_nodes = self.trajectory_tree_builder.get_best_nodes_global(self.trajectory_objective_set, self.BEST_RANDOM_NODES_K)

            for parent_node in best_nodes:
                if parent_node.id not in self.trajectory_tree_builder.node_list:
                    continue

                new_nodes = self.trajectory_tree_builder.steer_actors(parent_node, self.trajectory_objective_set)
                if self.VERBOSE:
                    print(f"New nodes: {len(new_nodes)}")
                if all(new_node.monitor_result_map_set.is_failed() for new_node in new_nodes):  # or len(new_nodes) == 0:
                    # print(f"Removed branch until parent with multiple children: {parent_node.id}")
                    if self.VERBOSE:
                        for new_node in new_nodes:
                            self.print_maneuver_states(new_node)
                    self.trajectory_tree_builder.remove_branch_until_parent_with_multiple_children(parent_node)
                    # self.trajectory_tree_builder.remove_branch_until_previous_actor_maneuver(parent_node)
                    continue

                for new_node in new_nodes:
                    if new_node.monitor_result_map_set.is_failed():
                        if self.VERBOSE:
                            for rel, rules in new_node.monitor_result_map_set.get_failed_rules().items():
                                print(f"Failed in {rel} context: {rules}")
                        continue
                    self.trajectory_tree_builder.add_node(parent_node, new_node)
                    if self.VERBOSE:
                        self.print_maneuver_states(new_node)

            self.end_iteration()
            # sleep(0.5)
            continue
            # if it does not collide
            # find nearest nodes to new_node
            nearest_indexes = self.find_near_nodes(new_node, radius_multiplier=5)
            # from those nearest nodes find the best parent to new_node
            found_parent = self.choose_parent(new_node, nearest_indexes)
            if not found_parent:
                self.end_iteration()
                continue

            # add new_node to node_list
            new_node_id = self.trajectory_tree_builder.add_node(new_node)
            # make new_node a parent of another node if necessary
            self.rewire(new_node_id, new_node, nearest_indexes)
            self.node_list[new_node.parent].children.add(new_node_id)

            if len(self.trajectory_tree_builder) > self.MAX_NODES:
                self.trajectory_tree_builder.prune_branches()

            self.end_iteration()

        # generate course
        last_node = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)
        trajectories, node_path = self.trajectory_tree_builder.get_path_trajectories(last_node)
        return trajectories

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

        best_node = self.trajectory_tree_builder.get_best_leaf_global(self.trajectory_objective_set)
        self.trajectory_objective_set.push_out_goal_positions(best_node)

        self._iteration_count += 1
        self._notify_observer()

    def _notify_observer(self) -> None:
        if self._observer is None:
            return
        if self._iteration_count % self.ANIM_UPDATE_INTERVAL != 0:
            return
        try:
            best = self.current_best_trajectories()
        except Exception:
            return
        if best is not None:
            self._observer(best, self._iteration_count)

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
