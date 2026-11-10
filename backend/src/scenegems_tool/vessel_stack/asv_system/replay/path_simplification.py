"""Path thinning for ArduPilot mission upload.

Trajectories are resampled at 1 to 2 second steps, so a mission built one
``NAV_WAYPOINT`` per state can hold several hundred closely spaced points. An
ArduRover then treats the whole path as one continuous corner: it never reaches
``WP_SPEED`` and, on skid-steer hulls, pivots at almost every point. Collapsing
the near-collinear runs to their endpoints lets the waypoint navigation
controller build smooth legs while keeping every real corner of the path.
"""

from typing import List

import numpy as np

from concrete_level.models.actor_state import ActorState


def _rdp_keep_indices(points: List[np.ndarray], epsilon_m: float) -> List[int]:
    """Ramer-Douglas-Peucker simplification (iterative).

    Returns the sorted indices of the points to keep: the two endpoints plus
    every point whose perpendicular distance from the running chord exceeds
    ``epsilon_m``. Corners are preserved exactly; points on a straight run are
    dropped.
    """
    n = len(points)
    if n <= 2:
        return list(range(n))

    keep = [False] * n
    keep[0] = True
    keep[n - 1] = True
    stack = [(0, n - 1)]

    while stack:
        start, end = stack.pop()
        if end <= start + 1:
            continue
        a = points[start]
        b = points[end]
        ab = b - a
        ab_len = float(np.linalg.norm(ab))

        max_dist = -1.0
        max_idx = -1
        for i in range(start + 1, end):
            d = points[i] - a
            if ab_len < 1e-9:
                dist = float(np.linalg.norm(d))
            else:
                # Perpendicular distance from point i to segment a-b, via the
                # 2-D cross product magnitude (avoids np.cross 2-D deprecation).
                dist = float(abs(ab[0] * d[1] - ab[1] * d[0]) / ab_len)
            if dist > max_dist:
                max_dist = dist
                max_idx = i

        if max_dist > epsilon_m and max_idx != -1:
            keep[max_idx] = True
            stack.append((start, max_idx))
            stack.append((max_idx, end))

    return [i for i, k in enumerate(keep) if k]


def simplify_state_path(
    states: List[ActorState],
    *,
    epsilon_m: float,
) -> List[ActorState]:
    """Thin a densely sampled state path for ArduPilot mission upload.

    Runs Ramer-Douglas-Peucker on the state positions with tolerance
    ``epsilon_m``: near-collinear points on straight legs are removed while
    corners (and the genuine curvature of evasive arcs) are preserved. The
    first and last states are always kept, and the result is always a
    subsequence of the input. Inputs with fewer than three states, and any
    non-positive ``epsilon_m``, are returned unchanged.
    """
    if len(states) < 3 or epsilon_m <= 0.0:
        return list(states)

    points = [s.p for s in states]
    kept_idx = _rdp_keep_indices(points, epsilon_m)

    if len(kept_idx) < 2:
        kept_idx = [0, len(states) - 1]

    return [states[i] for i in kept_idx]
