import math
import random
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from utils.global_constants import PHANTOM_SHIP_ANGLE

# Add src directory to path for imports
src_path = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))

from utils.math_utils import rotate_heading
from utils.safety_domains import RectangularSafetyDomain

# Constants
DEFAULT_FIGURE_SIZE = (8, 8)
DEFAULT_DEMO_FIGURE_SIZE = (10, 8)
DISTANCE_SCALING_FACTOR = 0.25


def plot_rectangle(center_x: float, center_y: float, a: float, b: float, theta: float, ax=None, **kwargs) -> plt.Axes:
    """
    Plot a rectangle with given center, length (a), width (b), and orientation.

    Parameters:
    -----------
    center_x, center_y : float
        Center coordinates of the rectangle
    a, b : float
        Half-length and half-width of the rectangle (a along heading direction, b perpendicular)
    theta : float
        Rotation angle in radians (counterclockwise from positive x-axis)
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates a new figure
    **kwargs : dict
        Additional arguments passed to plt.plot() (color, linewidth, etc.)

    Returns:
    --------
    matplotlib.axes.Axes
        The axes object used for plotting
    """
    # Define rectangle corners in local coordinate system (before rotation)
    # a is half-length along heading, b is half-width perpendicular
    corners_local = np.array(
        [
            [-a, -b],  # Bottom-left
            [a, -b],  # Bottom-right
            [a, b],  # Top-right
            [-a, b],  # Top-left
            [-a, -b],  # Close the rectangle
        ]
    )

    # Create rotation matrix
    cos_theta, sin_theta = np.cos(theta), np.sin(theta)
    rotation_matrix = np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]])

    # Apply rotation using matrix multiplication
    rotated_corners = corners_local @ rotation_matrix.T

    # Translate to center using vectorized addition
    final_corners = rotated_corners + np.array([center_x, center_y])

    # Create plot if no axes provided
    if ax is None:
        fig, ax = plt.subplots(figsize=DEFAULT_FIGURE_SIZE)

    # Plot the rectangle
    ax.plot(final_corners[:, 0], final_corners[:, 1], **kwargs)

    # Mark the center
    ax.plot(center_x, center_y, "ro", markersize=8, label="Phantom ship")

    # Add axes for reference
    ax.axhline(y=0, color="k", linestyle="-", alpha=0.3)
    ax.axvline(x=0, color="k", linestyle="-", alpha=0.3)

    # Set equal aspect ratio and grid
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend()

    return ax


def plot_rectangle_with_axes(rectangular_safety_domain: RectangularSafetyDomain, ax=None, **kwargs) -> plt.Axes:
    """
    Plot a rectangle with its length and width axes shown.

    Parameters:
    -----------
    rectangular_safety_domain: RectangularSafetyDomain
        The rectangular safety domain to plot
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates a new figure
    **kwargs : dict
        Additional arguments passed to plt.plot() (color, linewidth, etc.)

    Returns:
    --------
    matplotlib.axes.Axes
        The axes object used for plotting
    """
    # Plot the rectangle
    ax = plot_rectangle(
        rectangular_safety_domain.center[0],
        rectangular_safety_domain.center[1],
        rectangular_safety_domain.a,
        rectangular_safety_domain.b,
        rectangular_safety_domain.heading,
        ax,
        **kwargs,
    )

    # Calculate axis endpoints using vectorized operations
    center = np.array([rectangular_safety_domain.center[0], rectangular_safety_domain.center[1]])
    cos_theta, sin_theta = np.cos(rectangular_safety_domain.heading), np.sin(rectangular_safety_domain.heading)

    # Length axis vectors (along heading direction, a)
    length_direction = np.array([cos_theta, sin_theta])
    length_axis_points = np.column_stack([center - rectangular_safety_domain.a * length_direction, center + rectangular_safety_domain.a * length_direction])

    # Width axis vectors (perpendicular to heading, b)
    width_direction = np.array([-sin_theta, cos_theta])
    width_axis_points = np.column_stack([center - rectangular_safety_domain.b * width_direction, center + rectangular_safety_domain.b * width_direction])

    # Plot axes
    ax.plot(length_axis_points[0, :], length_axis_points[1, :], "r--", linewidth=2, label="Length axis (a)")
    ax.plot(width_axis_points[0, :], width_axis_points[1, :], "b--", linewidth=2, label="Width axis (b)")

    ax.legend()
    return ax


def demo_rectangle_visualization():
    """Demonstrate rectangle visualization with intersection calculation."""
    # Configuration parameters

    real_center = np.array([3.1, 5.2])
    # 10 random points
    random_points = np.array([[random.uniform(0, 10), random.uniform(0, 10)] for _ in range(10)])

    for heading in range(-300, 300, 30):
        direction_angle = rotate_heading(heading, -PHANTOM_SHIP_ANGLE)
        half_length = 5
        half_width = 3

        rectangular_safety_domain = RectangularSafetyDomain(real_center, heading, half_length, half_width)
        intersection = rectangular_safety_domain.intersection_of_line_from_center(direction_angle)

        # Calculate distance and scaled point using vectorized operations
        distance = np.linalg.norm(intersection - real_center)
        scaled_direction = rotate_heading(heading, -PHANTOM_SHIP_ANGLE)
        direction_vector = np.array([np.cos(scaled_direction), np.sin(scaled_direction)])

        new_rectangular_safety_domain = rectangular_safety_domain.shift(distance / 4, scaled_direction)

        for i, point in enumerate(random_points):
            print(f"Point {i} is in rectangle: {new_rectangular_safety_domain.contains_point(point)}")

        # Create visualization
        fig, ax = plt.subplots(figsize=DEFAULT_DEMO_FIGURE_SIZE)

        # Plot rectangle with axes
        plot_rectangle_with_axes(new_rectangular_safety_domain, ax=ax, color="purple", linewidth=2)

        # Configure plot
        ax.set_title(f"Rectangle Visualization\n" f"Center: ({real_center[0]:.3f}, {real_center[1]:.3f}), " f"a={half_length}, b={half_width}, θ={math.degrees(direction_angle):.1f}°")
        ax.set_xlim(real_center[0] - 8, real_center[0] + 8)
        ax.set_ylim(real_center[1] - 6, real_center[1] + 6)

        # Plot the scaled point
        ax.plot(real_center[0], real_center[1], "bo", markersize=8, label="Real ship")

        # plot the random points with index label
        for i, point in enumerate(random_points):
            ax.text(point[0], point[1], f"{i}", fontsize=12)
            ax.plot(point[0], point[1], "go", markersize=8, label="Random point")

        # Draw line from center to intersection using vectorized operations
        line_end = new_rectangular_safety_domain.center + distance * -direction_vector
        line_points = np.column_stack([new_rectangular_safety_domain.center, line_end])
        ax.plot(line_points[0, :], line_points[1, :], "r-", linewidth=2, label="Line from center to intersection")

        # plot left point, right point, beginning point, ending point
        ax.plot(new_rectangular_safety_domain.left_point[0], new_rectangular_safety_domain.left_point[1], "g*", markersize=8, label="Left point")
        ax.plot(new_rectangular_safety_domain.right_point[0], new_rectangular_safety_domain.right_point[1], "g*", markersize=8, label="Right point")
        ax.plot(new_rectangular_safety_domain.back_point[0], new_rectangular_safety_domain.back_point[1], "g*", markersize=8, label="Beginning point")
        ax.plot(new_rectangular_safety_domain.front_point[0], new_rectangular_safety_domain.front_point[1], "g*", markersize=8, label="Ending point")
        ax.plot(new_rectangular_safety_domain.center[0], new_rectangular_safety_domain.center[1], "g*", markersize=8, label="Center")
        ax.plot(intersection[0], intersection[1], "r*", markersize=8, label="Intersection")
        ax.plot(direction_vector[0], direction_vector[1], "b*", markersize=8, label="Direction vector")
        ax.plot(new_rectangular_safety_domain.v[0], new_rectangular_safety_domain.v[1], "y*", markersize=8, label="V")
        ax.plot(new_rectangular_safety_domain.v_perp_left[0], new_rectangular_safety_domain.v_perp_left[1], "y*", markersize=8, label="V perp left")
        ax.plot(new_rectangular_safety_domain.v_perp_right[0], new_rectangular_safety_domain.v_perp_right[1], "y*", markersize=8, label="V perp right")
        ax.plot(new_rectangular_safety_domain.v_perp_left[0], new_rectangular_safety_domain.v_perp_left[1], "y*", markersize=8, label="V perp left")

        # put labels on the points
        ax.text(new_rectangular_safety_domain.left_point[0], new_rectangular_safety_domain.left_point[1], "Left point", fontsize=12)
        ax.text(new_rectangular_safety_domain.right_point[0], new_rectangular_safety_domain.right_point[1], "Right point", fontsize=12)
        ax.text(new_rectangular_safety_domain.back_point[0], new_rectangular_safety_domain.back_point[1], "Beginning point", fontsize=12)
        ax.text(new_rectangular_safety_domain.front_point[0], new_rectangular_safety_domain.front_point[1], "Ending point", fontsize=12)
        ax.text(new_rectangular_safety_domain.center[0], new_rectangular_safety_domain.center[1], "Center", fontsize=12)
        ax.text(intersection[0], intersection[1], "Intersection", fontsize=12)
        ax.text(direction_vector[0], direction_vector[1], "Direction vector", fontsize=12)
        ax.text(new_rectangular_safety_domain.v[0], new_rectangular_safety_domain.v[1], "V", fontsize=12)
        ax.text(new_rectangular_safety_domain.v_perp_left[0], new_rectangular_safety_domain.v_perp_left[1], "V perp left", fontsize=12)
        ax.text(new_rectangular_safety_domain.v_perp_right[0], new_rectangular_safety_domain.v_perp_right[1], "V perp right", fontsize=12)
        ax.text(new_rectangular_safety_domain.v_perp_left[0], new_rectangular_safety_domain.v_perp_left[1], "V perp left", fontsize=12)
        # put labels on the lines
        ax.text(line_points[0, 0], line_points[1, 0], "Line from center to intersection", fontsize=12)
        ax.text(line_points[0, 1], line_points[1, 1], "Line from center to intersection", fontsize=12)

        ax.legend()
        plt.show()


if __name__ == "__main__":
    demo_rectangle_visualization()
