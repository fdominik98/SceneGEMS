import random
from itertools import product
from typing import Dict, List, Optional, Set, Tuple

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverStateSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults, MonitoredTrajectory
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from utils.global_constants import EPSILON, MAX_DISTANCE
from utils.interval import Interval
from utils.math_utils import calculate_heading, distance, heading_diff, rotate_heading
from utils.safety_domains import DomainCollection, RectangularSafetyDomain


class SceneNode:
    def __init__(self, monitored_scene_with_results: MonitoredSceneWithResults):
        self.monitored_scene_with_results = monitored_scene_with_results
        self.id = -1
        self.parent: Optional[int] = None
        self.children: Set[int] = set()

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
    def __init__(self, actor: ConcreteActor, root: SceneNode, time_step: int, verbose: bool = False):
        self.actor = actor
        self.relation = Relation(actor, actor)
        self.time_step = time_step
        self.start_state = root.scene[self.actor]
        self.potential_collision_domain = self.calculate_bounding_rect(root)
        self.verbose = verbose

        if self.potential_collision_domain.empty:
            self.start_goal_distance = MAX_DISTANCE
        else:
            start_domain_end_point_distance = distance(self.start_state.p, self.potential_collision_domain.bounding_rectangle.front_point)
            start_domain_center_distance = distance(self.start_state.p, self.potential_collision_domain.bounding_rectangle.center)
            self.start_goal_distance = start_domain_end_point_distance + start_domain_center_distance
        self.goal_position = self.actor.simulate_distance(self.start_state, self.start_goal_distance).p

    def calculate_bounding_rect(self, node: SceneNode) -> DomainCollection:
        domains = DomainCollection()
        for situation_context, colregs_state in node.monitored_scene_with_results.colregs_states_with_context:
            if not situation_context.is_give_way_actor(self.actor):
                continue
            if any(colregs_state.actors_in_front_of_potential_collision_domain.values()):
                continue
            domains = domains.union(situation_context.start_potential_collision_domains[self.actor])
        return domains

    def calculate_cost(self, node: SceneNode) -> float:
        actor_state = node.scene[self.actor]

        distance_to_goal_course = self.start_state.point_distance_from_course(actor_state.p)
        distance_to_goal = distance(actor_state.p, self.goal_position)

        # distance_to_safety_domain = 0.0
        distance_to_safety_domain_avoidance_side = 0.0
        domains = self.calculate_bounding_rect(node)
        if not domains.empty:
            # distance_to_safety_domain = bounding_rect.distance_from_point(actor_state.p)
            avoidance_direction = node.monitored_scene_with_results.situation_context_set.actor_avoidance_direction(self.actor)
            distance_to_safety_domain_avoidance_side = domains.bounding_rectangle.distance_from_direction(actor_state.p, avoidance_direction)
        # maneuver_count = node.monitored_scene_with_results.maneuver_state_set[self.relation].maneuver_count
        # average_distance_per_maneuver = node.monitored_scene_with_results.maneuver_state_set[self.relation].total_distance_made / maneuver_count

        timestamp = node.monitored_scene_with_results.timestamp
        if timestamp == 0 or self.actor.max_speed == 0.0:
            distance_from_start_under_timestamp = 0.0
            distance_from_start_under_timestamp_norm = 0.0
        else:
            distance_from_start_under_timestamp = distance(actor_state.p, self.start_state.p) / node.monitored_scene_with_results.timestamp
            distance_from_start_under_timestamp_norm = distance_from_start_under_timestamp / self.actor.max_speed

        distance_to_goal_course_norm = distance_to_goal_course / MAX_DISTANCE
        distance_to_goal_norm = distance_to_goal / MAX_DISTANCE
        # distance_to_safety_domain_norm = distance_to_safety_domain / gc.MAX_DISTANCE
        # average_distance_per_maneuver_norm = average_distance_per_maneuver / (gc.MAX_DISTANCE / maneuver_count)

        if self.verbose and False:
            print(f"Distance to goal course: {distance_to_goal_course}, norm: {distance_to_goal_course_norm}")
            print(f"Distance to goal: {distance(actor_state.p, self.goal_position)}, norm: {distance_to_goal_norm}")
            print(f"Distance to safety domain: {distance_to_safety_domain}, norm: {distance_to_safety_domain_norm}")
            # print(f"Average distance per maneuver: {average_distance_per_maneuver}, norm: {average_distance_per_maneuver_norm}")
            print(f"Distance per timestamp: {distance_from_start_under_timestamp}, norm: {distance_from_start_under_timestamp_norm}")

        return (
            distance_to_goal_course
            + distance_to_goal
            # + distance_to_safety_domain
            + distance_to_safety_domain_avoidance_side
            # - average_distance_per_maneuver / 10
            - distance_from_start_under_timestamp
        )

    def push_out_goal_position(self, node: SceneNode):
        state = node.scene[self.actor]
        distance_threshold = self.actor.distance_made(state, (state.heading, state.speed), self.time_step * 3)
        if distance(state.p, self.goal_position) >= distance_threshold:
            return
        u_ref = (self.start_state.heading, state.speed)
        plus_distance = self.actor.distance_made(self.start_state, u_ref, self.time_step * 10)
        self.start_goal_distance += plus_distance
        self.goal_position = self.actor.simulate_distance(self.start_state, self.start_goal_distance).p


class TrajectoryObjectiveSet(Dict[ConcreteActor, TrajectoryObjective]):
    def __init__(self, root: SceneNode, time_step: int, goal_sample_rate: int, verbose: bool = False):
        super().__init__({actor: TrajectoryObjective(actor, root, time_step, verbose) for actor in root.scene.actors})
        self.goal_sample_rate = goal_sample_rate

    def calculate_cost(self, node: SceneNode) -> float:
        return sum(trajectory_objective.calculate_cost(node) for trajectory_objective in self.values())

    def push_out_goal_positions(self, node: SceneNode):
        for trajectory_objective in self.values():
            trajectory_objective.push_out_goal_position(node)

    def get_suggested_headings(self, node: SceneNode) -> List[Dict[ConcreteActor, float]]:
        suggested_headings = {}
        suggested_maneuvers = node.maneuver_suggestions
        for actor, trajectory_objective in self.items():
            state = node.scene[actor]
            colregs_constants = node.maneuver_state_set[Relation(actor, actor)].colregs_constants
            suggested_ranges = suggested_maneuvers.get_suggested_range_of_heading_change(
                actor, trajectory_objective.time_step, colregs_constants
            )

            if trajectory_objective.verbose:
                print(f"{actor.name}: Suggested maneuvers: {suggested_maneuvers.get_all_maneuvers(actor)}")
                print(f"{actor.name}: Suggested maneuvers info: {suggested_maneuvers.get_info(actor)}")
                print(f"{actor.name}: Suggested ranges: {suggested_ranges}")

            if suggested_ranges.empty:
                if trajectory_objective.verbose:
                    print(f"WARNING: No suggested ranges found for {actor.name}")
                return []

            if self.goal_sample_rate > random.randint(0, 100):
                to_goal_heading = calculate_heading(trajectory_objective.goal_position - state.p)
                to_goal_heading_diff = heading_diff(to_goal_heading, state.heading)
                to_goal_heading_change_interval = Interval.closed(0, to_goal_heading_diff)
                if to_goal_heading_change_interval.empty:
                    to_goal_heading_change_interval = Interval.closed(-EPSILON, EPSILON)
                random_heading_changes = suggested_ranges.intersection(to_goal_heading_change_interval).sample_from_all()
                if trajectory_objective.verbose and False:
                    print(f"{actor.name}: To goal heading change interval: {to_goal_heading_change_interval}")
                    print(f"{actor.name}: Suggested ranges after goal sample: {suggested_ranges}")
            else:
                random_heading_changes = suggested_ranges.sample_from_all()

            random_headings = [rotate_heading(state.heading, random_heading_change) for random_heading_change in random_heading_changes]
            suggested_headings[actor] = random_headings

        # convert to List[Dict[ConcreteActor, float]] by taking the product of the suggested ranges
        return self.combine_headings(suggested_headings)

    @staticmethod
    def combine_headings(headings: Dict[ConcreteActor, List[float]]) -> List[Dict[ConcreteActor, float]]:
        if not headings:
            return []

        # Compute Cartesian product of headings
        actors = list(headings.keys())
        lists = [headings[a] for a in actors]

        result = []
        for combo in product(*lists):
            entry = {actor: heading for actor, heading in zip(actors, combo)}
            result.append(entry)

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
        for headings in suggested_headings:
            next_scene = SceneBuilder()
            for actor, heading in headings.items():
                actor_state = nearest_node.scene[actor]
                next_state = actor.simulate(actor_state, (heading, actor_state.speed), self.time_step)
                next_scene.set_state(actor, next_state)
            monitored_scene_with_results = self.monitor.step(nearest_node.monitored_scene_with_results, next_scene.build(), self.time_step)
            next_node = SceneNode(monitored_scene_with_results=monitored_scene_with_results)
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
