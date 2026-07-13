from typing import Dict, List, Tuple

import numpy as np
import pygame

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.trajectory_generation.trajectory_tree_builder import TrajectoryObjective, TrajectoryObjectiveSet, TrajectoryTreeBuilder
from utils import colors
from utils.global_constants import MAX_COORD


class RRTStarVisualizer:
    ANIM_DIM: int = 1000
    SCALER = ANIM_DIM / (MAX_COORD * 2)
    WINDOW_SIZE = [ANIM_DIM, ANIM_DIM]

    def __init__(
        self,
        trajectory_tree_builder: TrajectoryTreeBuilder,
        trajectory_objective_set: TrajectoryObjectiveSet,
    ) -> None:
        self.trajectory_tree_builder = trajectory_tree_builder
        self.trajectory_objective_set = trajectory_objective_set
        self.start_scene = trajectory_tree_builder.root.scene
        self.sample_area = [(0, MAX_COORD * 2), (0, MAX_COORD * 2)]

        pygame.init()
        self.screen = pygame.display.set_mode(self.WINDOW_SIZE)

        self.domain_bounding_rect_markers = self.create_domain_bounding_rect_markers()

    def create_domain_bounding_rect_markers(self):
        rect_markers: Dict[ConcreteActor, List[Tuple[np.ndarray, np.ndarray]]] = {}
        for trajectory_objective in self.trajectory_objective_set.values():
            if trajectory_objective.potential_collision_domain.empty:
                continue
            potential_collision_domain = trajectory_objective.potential_collision_domain.bounding_rectangle
            left_shift = potential_collision_domain.b * potential_collision_domain.v_perp_left
            forward_shift = potential_collision_domain.a * potential_collision_domain.v
            front_line = (
                potential_collision_domain.front_point + left_shift,
                potential_collision_domain.front_point - left_shift,
            )
            left_line = (
                potential_collision_domain.left_point + forward_shift,
                potential_collision_domain.left_point - forward_shift,
            )
            right_line = (
                potential_collision_domain.right_point - forward_shift,
                potential_collision_domain.right_point + forward_shift,
            )
            back_line = (
                potential_collision_domain.back_point - left_shift,
                potential_collision_domain.back_point + left_shift,
            )
            rect_markers[trajectory_objective.actor] = [front_line, left_line, right_line, back_line]
        return rect_markers

    def draw_obstacles(self):
        print(self.domain_bounding_rect_markers)
        for actor, domain_markers in self.domain_bounding_rect_markers.items():
            for line_marker in domain_markers:
                pygame.draw.line(self.screen, colors.to_rgb(colors.colors[actor.id]), self.reverse_coord(line_marker[0]), self.reverse_coord(line_marker[1]), 3)

    def draw_branches(self, trajectory_objective: TrajectoryObjective):
        start_state = trajectory_objective.start_state
        actor = trajectory_objective.actor
        pygame.draw.circle(self.screen, colors.to_rgb(colors.colors[actor.id]), self.reverse_coord(start_state.p), 7)
        pygame.draw.circle(self.screen, colors.to_rgb(colors.light_colors[actor.id]), self.reverse_coord(trajectory_objective.goal_position), 7)
        # Branches
        for node in self.trajectory_tree_builder.nodes:
            if not node.is_root:
                parent = self.trajectory_tree_builder.parent(node)
                pygame.draw.line(
                    self.screen,
                    (0, 255, 0),
                    self.reverse_coord(parent.scene[trajectory_objective.actor].p),
                    self.reverse_coord(node.scene[trajectory_objective.actor].p),
                )
        # Draw leaves
        for node in self.trajectory_tree_builder.leaves:
            pygame.draw.circle(self.screen, (255, 0, 255), self.reverse_coord(node.scene[trajectory_objective.actor].p), 2)

        # Final path
        best_node = self.trajectory_tree_builder.get_best_node(trajectory_objective)
        path = self.trajectory_tree_builder.get_path(best_node)

        ind = len(path)
        while ind > 1:
            for trajectory_objective in self.trajectory_objective_set.values():
                color = colors.to_rgb(colors.colors[trajectory_objective.actor.id])
                pygame.draw.line(
                    self.screen,
                    color,
                    self.reverse_coord(path[ind - 2].scene[trajectory_objective.actor].p),
                    self.reverse_coord(path[ind - 1].scene[trajectory_objective.actor].p),
                    1,
                )
            ind -= 1

    def update(self, iteration_count: int):
        self.screen.fill((255, 255, 255))
        self.draw_obstacles()
        for trajectory_objective in self.trajectory_objective_set.values():
            self.draw_branches(trajectory_objective)
        self.draw_information_texts(iteration_count)

        pygame.display.update()

    def draw_information_texts(self, iteration_count: int):
        # Write the cost of the closest node to the goal in the right top corner
        font = pygame.font.Font(None, 36)
        # Write the number of nodes in the left top corner
        text = font.render(f"Nodes: {len(self.trajectory_tree_builder.nodes)}", True, (0, 0, 0))
        self.screen.blit(text, (10, 90))

        # Write the number of leaves in the left top corner
        text = font.render(f"Leaves: {len(self.trajectory_tree_builder.leaves)}", True, (0, 0, 0))
        self.screen.blit(text, (10, 130))

        # Write the number of iterations in the left bottom corner
        text = font.render(f"Iterations: {iteration_count}", True, (0, 0, 0))
        self.screen.blit(text, (10, 170))

    def handle_user_input(self) -> bool:
        for e in pygame.event.get():
            if e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 1:
                    # coords = self.inverse_reverse_coord(np.array(e.pos))
                    # self.obstacle_list.append(CircularObstacle(coords, 3000))
                    # path_validation()
                    pass
                elif e.button == 3:
                    goal_position = self.inverse_reverse_coord(np.array(e.pos))
                    # path_validation()
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_SPACE:
                    return True
                elif e.key == pygame.K_ESCAPE:
                    exit(0)
                elif e.key == pygame.K_t:
                    self.draw_tree_structure_in_matplotlib()
        return False

    def reverse_coord(self, coords: np.ndarray):
        return np.array(
            [
                (coords[0] - self.sample_area[0][0]) * self.SCALER + 50,
                self.ANIM_DIM - (coords[1] - self.sample_area[1][0]) * self.SCALER - 50,
            ]
        )

    def inverse_reverse_coord(self, coords: np.ndarray):
        return np.array(
            [
                (coords[0] - 50) / self.SCALER + self.sample_area[0][0],
                (self.ANIM_DIM - coords[1] - 50) / self.SCALER + self.sample_area[1][0],
            ]
        )

    def draw_tree_structure_in_matplotlib(self) -> None:
        # draw the tree structure in matplotlib
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots()
        node_list = self.trajectory_tree_builder.node_list
        for trajectory_objective in self.trajectory_objective_set.values():
            for node in node_list.values():
                if node.parent is not None:
                    ax.plot(
                        [node.scene[trajectory_objective.actor].p[0], node_list[node.parent].scene[trajectory_objective.actor].p[0]],
                        [node.scene[trajectory_objective.actor].p[1], node_list[node.parent].scene[trajectory_objective.actor].p[1]],
                    )
        plt.show()
