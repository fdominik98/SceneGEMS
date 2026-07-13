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
from utils.safety_domains import EllipticalSafetyDomain

# Constants
ELLIPSE_POINTS = 1000
DEFAULT_FIGURE_SIZE = (8, 8)
DEFAULT_DEMO_FIGURE_SIZE = (10, 8)
DISTANCE_SCALING_FACTOR = 0.25


def plot_ellipse(center_x: float, center_y: float, a: float, b: float, theta: float, ax=None, **kwargs) -> plt.Axes:
    """
    Plot an ellipse with given center, semi-major axis (a), semi-minor axis (b), and orientation.

    Parameters:
    -----------
    center_x, center_y : float
        Center coordinates of the ellipse
    a, b : float
        Semi-major and semi-minor axis lengths
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

    # Create parameter t for the ellipse
    t = np.linspace(0, 2 * np.pi, ELLIPSE_POINTS)

    # Parametric equations for ellipse centered at origin (vectorized)
    ellipse_points = np.column_stack([a * np.cos(t), b * np.sin(t)])

    # Create rotation matrix
    cos_theta, sin_theta = np.cos(theta), np.sin(theta)
    rotation_matrix = np.array([[cos_theta, -sin_theta], [sin_theta, cos_theta]])

    # Apply rotation using matrix multiplication
    rotated_points = ellipse_points @ rotation_matrix.T

    # Translate to center using vectorized addition
    final_points = rotated_points + np.array([center_x, center_y])

    # Create plot if no axes provided
    if ax is None:
        fig, ax = plt.subplots(figsize=DEFAULT_FIGURE_SIZE)

    # Plot the ellipse
    ax.plot(final_points[:, 0], final_points[:, 1], **kwargs)

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


def plot_ellipse_with_axes(elliptic_safety_domain: EllipticalSafetyDomain, ax=None, **kwargs) -> plt.Axes:
    """
    Plot an ellipse with its major and minor axes shown.

    Parameters:
    -----------
    elliptic_safety_domain: EllipticSafetyDomain
        Center coordinates of the ellipse
    a, b : float
        Semi-major and semi-minor axis lengths
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

    # Plot the ellipse
    ax = plot_ellipse(
        elliptic_safety_domain.center[0],
        elliptic_safety_domain.center[1],
        elliptic_safety_domain.a,
        elliptic_safety_domain.b,
        elliptic_safety_domain.heading,
        ax,
        **kwargs,
    )

    # Calculate axis endpoints using vectorized operations
    center = np.array([elliptic_safety_domain.center[0], elliptic_safety_domain.center[1]])
    cos_theta, sin_theta = np.cos(elliptic_safety_domain.heading), np.sin(elliptic_safety_domain.heading)

    # Major axis vectors
    major_direction = np.array([cos_theta, sin_theta])
    major_axis_points = np.column_stack([center - elliptic_safety_domain.a * major_direction, center + elliptic_safety_domain.a * major_direction])

    # Minor axis vectors
    minor_direction = np.array([-sin_theta, cos_theta])
    minor_axis_points = np.column_stack([center - elliptic_safety_domain.b * minor_direction, center + elliptic_safety_domain.b * minor_direction])

    # Plot axes
    ax.plot(major_axis_points[0, :], major_axis_points[1, :], "r--", linewidth=2, label="Major axis")
    ax.plot(minor_axis_points[0, :], minor_axis_points[1, :], "b--", linewidth=2, label="Minor axis")

    ax.legend()
    return ax


def demo_ellipse_visualization():
    """Demonstrate ellipse visualization with intersection calculation."""
    # Configuration parameters

    real_center = np.array([3.1, 5.2])
    # 10 random points
    random_points = np.array([[random.uniform(0, 10), random.uniform(0, 10)] for _ in range(10)])

    for heading in range(-300, 300, 30):
        direction_angle = rotate_heading(heading, -PHANTOM_SHIP_ANGLE)
        semi_major_axis = 5
        semi_minor_axis = 3

        elliptic_safety_domain = EllipticalSafetyDomain(real_center, heading, semi_major_axis, semi_minor_axis)
        intersection = elliptic_safety_domain.intersection_of_line_from_point(real_center, direction_angle)

        # Calculate distance and scaled point using vectorized operations
        distance = np.linalg.norm(intersection - real_center)
        scaled_direction = rotate_heading(heading, -PHANTOM_SHIP_ANGLE)
        direction_vector = np.array([np.cos(scaled_direction), np.sin(scaled_direction)])

        new_elliptic_safety_domain = elliptic_safety_domain.shift(distance / 4, scaled_direction)

        for i, point in enumerate(random_points):
            print(f"Point {i} is in ellipse: {new_elliptic_safety_domain.contains_point(point)}")

        # Create visualization
        fig, ax = plt.subplots(figsize=DEFAULT_DEMO_FIGURE_SIZE)

        # Plot ellipse with axes
        plot_ellipse_with_axes(new_elliptic_safety_domain, ax=ax, color="purple", linewidth=2)

        # Configure plot
        ax.set_title(f"Ellipse Visualization\n" f"Center: ({real_center[0]:.3f}, {real_center[1]:.3f}), " f"a={semi_major_axis}, b={semi_minor_axis}, θ={math.degrees(direction_angle):.1f}°")
        ax.set_xlim(real_center[0] - 8, real_center[0] + 8)
        ax.set_ylim(real_center[1] - 6, real_center[1] + 6)

        # Plot the scaled point
        ax.plot(real_center[0], real_center[1], "bo", markersize=8, label="Real ship")

        # plot the random points with index label
        for i, point in enumerate(random_points):
            ax.text(point[0], point[1], f"{i}", fontsize=12)
            ax.plot(point[0], point[1], "go", markersize=8, label="Random point")

        # Draw line from center to intersection using vectorized operations
        line_end = new_elliptic_safety_domain.center + distance * -direction_vector
        line_points = np.column_stack([new_elliptic_safety_domain.center, line_end])
        ax.plot(line_points[0, :], line_points[1, :], "r-", linewidth=2, label="Line from center to intersection")

        # plot lines from random points to intersection with the random point to direction if the point is in the ellipse
        for i, point in enumerate(random_points):
            if new_elliptic_safety_domain.contains_point(point):
                intersection = new_elliptic_safety_domain.intersection_of_line_from_point(point, direction_angle)
                line_points = np.column_stack([point, intersection])
                ax.plot(line_points[0, :], line_points[1, :], "b-", linewidth=2, label="Line from random point to intersection")

        # plot lines from random points to intersection with the random point to direction if the point is not in the ellipse
        for i, point in enumerate(random_points):
            if not new_elliptic_safety_domain.contains_point(point):
                intersection = new_elliptic_safety_domain.intersection_of_line_from_point(point, direction_angle)
                line_points = np.column_stack([point, intersection])
                ax.plot(line_points[0, :], line_points[1, :], "g-", linewidth=2, label="Line from random point to intersection")

        ax.legend()
        plt.show()


if __name__ == "__main__":
    demo_ellipse_visualization()
