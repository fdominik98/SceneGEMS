import math
import random
import sys
from pathlib import Path

import matplotlib.patches
import matplotlib.pyplot as plt
import numpy as np

# Add src directory to path for imports
src_path = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))

from utils.safety_domains import CircularSafetyDomain, RectangularSafetyDomain

# Constants
DEFAULT_FIGURE_SIZE = (12, 10)


def plot_circle(center_x: float, center_y: float, radius: float, ax=None, **kwargs) -> plt.Axes:
    """
    Plot a circle with given center and radius.

    Parameters:
    -----------
    center_x, center_y : float
        Center coordinates of the circle
    radius : float
        Radius of the circle
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates a new figure
    **kwargs : dict
        Additional arguments passed to Circle patch (color, linewidth, fill, etc.)

    Returns:
    --------
    matplotlib.axes.Axes
        The axes object used for plotting
    """
    # Create plot if no axes provided
    if ax is None:
        fig, ax = plt.subplots(figsize=DEFAULT_FIGURE_SIZE)

    # Create circle patch
    circle = matplotlib.patches.Circle((center_x, center_y), radius, **kwargs)
    ax.add_patch(circle)

    return ax


def plot_circular_safety_domain(circular_safety_domain: CircularSafetyDomain, ax=None, **kwargs) -> plt.Axes:
    """
    Plot a CircularSafetyDomain object.

    Parameters:
    -----------
    circular_safety_domain: CircularSafetyDomain
        The circular safety domain to plot
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates a new figure
    **kwargs : dict
        Additional arguments passed to plot_circle() (color, linewidth, fill, etc.)

    Returns:
    --------
    matplotlib.axes.Axes
        The axes object used for plotting
    """
    return plot_circle(
        circular_safety_domain.center[0],
        circular_safety_domain.center[1],
        circular_safety_domain.radius,
        ax,
        **kwargs,
    )


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

    return ax


def plot_rectangular_safety_domain(rectangular_safety_domain: RectangularSafetyDomain, ax=None, **kwargs) -> plt.Axes:
    """
    Plot a RectangularSafetyDomain object.

    Parameters:
    -----------
    rectangular_safety_domain: RectangularSafetyDomain
        The rectangular safety domain to plot
    ax : matplotlib.axes.Axes, optional
        Axes to plot on. If None, creates a new figure
    **kwargs : dict
        Additional arguments passed to plot_rectangle() (color, linewidth, etc.)

    Returns:
    --------
    matplotlib.axes.Axes
        The axes object used for plotting
    """
    return plot_rectangle(
        rectangular_safety_domain.center[0],
        rectangular_safety_domain.center[1],
        rectangular_safety_domain.a,
        rectangular_safety_domain.b,
        rectangular_safety_domain.heading,
        ax,
        **kwargs,
    )


def demo_bound_circles():
    """Demonstrate bound_circles function by creating many circles and visualizing the result."""
    # Configuration parameters
    num_circles = 20
    center_range = (-15, 15)  # Range for center coordinates
    radius_range = (0.5, 3.0)  # Range for radius
    heading_range = (0, 2 * math.pi)  # Range for heading in radians

    # Generate random circles
    circles = []
    for i in range(num_circles):
        center = np.array([random.uniform(center_range[0], center_range[1]), random.uniform(center_range[0], center_range[1])])
        radius = random.uniform(radius_range[0], radius_range[1])
        heading = random.uniform(heading_range[0], heading_range[1])

        circle = CircularSafetyDomain(center, heading, radius)
        circles.append(circle)

    # Compute bounding rectangle
    bounding_rect = RectangularSafetyDomain.bound_domains(circles)

    # Create visualization
    fig, ax = plt.subplots(figsize=DEFAULT_FIGURE_SIZE)

    # Plot all individual circles in light colors
    for i, circle in enumerate(circles):
        plot_circular_safety_domain(circle, ax=ax, fill=False, edgecolor="lightblue", linewidth=1, alpha=0.6)
        # Mark centers of individual circles
        ax.plot(circle.center[0], circle.center[1], "bo", markersize=4, alpha=0.5)

    # Plot bounding rectangle in bold
    plot_rectangular_safety_domain(bounding_rect, ax=ax, color="red", linewidth=3, alpha=0.9, linestyle="--", label="Bounding Rectangle")

    # Mark center of bounding rectangle
    ax.plot(bounding_rect.center[0], bounding_rect.center[1], "ro", markersize=10, label="Bounding Center")

    # Configure plot
    ax.set_title(
        f"Bound Circles Test\n"
        f"Number of circles: {num_circles}\n"
        f"Bounding Rectangle: center=({bounding_rect.center[0]:.2f}, {bounding_rect.center[1]:.2f}), "
        f"a={bounding_rect.a:.2f}, b={bounding_rect.b:.2f}, "
        f"θ={math.degrees(bounding_rect.heading):.1f}°"
    )

    # Set appropriate axis limits with some padding
    all_centers = np.array([c.center for c in circles])
    all_centers = np.vstack([all_centers, bounding_rect.center])
    max_radius = max(c.radius for c in circles)
    margin = max_radius + 5
    ax.set_xlim(all_centers[:, 0].min() - margin, all_centers[:, 0].max() + margin)
    ax.set_ylim(all_centers[:, 1].min() - margin, all_centers[:, 1].max() + margin)

    # Add axes for reference
    ax.axhline(y=0, color="k", linestyle="-", alpha=0.3, linewidth=0.5)
    ax.axvline(x=0, color="k", linestyle="-", alpha=0.3, linewidth=0.5)

    # Set equal aspect ratio and grid
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_xlabel("X")
    ax.set_ylabel("Y")

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    demo_bound_circles()
