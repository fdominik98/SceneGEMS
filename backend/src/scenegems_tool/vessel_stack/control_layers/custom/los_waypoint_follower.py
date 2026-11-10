"""Line-of-sight waypoint follower of the custom controller: how it serves the replay ASV system.

The replay software hands the custom controller its trajectory as a waypoint mission: every
reference state is a waypoint, with the time the reference passes it. The follower steers by the
path's geometry and keeps the speed by its timing:

- heading: toward the point one lookahead along the path ahead of the vessel's projection onto
  it, moved across the path by the integral against a constant bias such as sideslip in a
  current or wind drift (asv_system/replay/line_of_sight.py gives the lookahead and the
  integral). On a straight leg this is the line of sight, course - atan((e + i) / lookahead).
  Ahead of a turn the point is already round the corner, so the vessel starts turning before
  the path does, by about the time its yaw rate takes to build up: a reference turning at the
  vessel's max turn rate cannot be caught up with afterwards, and the hulls came out of every
  turn 1 to 4 lengths wide when they followed only the leg they were on (WP6).
  The projection selects the leg, moving only forward, so a vessel that lags behind a turn
  still turns where the path turns instead of cutting across to where the reference is in time.
- speed: the reference speed at the step's target time, plus the distance along the path to
  where the reference is at the step's time, closed in catch_up_s but no faster than the vessel
  can brake (line_of_sight.catch_up_speed), within 0 and the vessel's max speed.
"""

import math
from typing import Optional, Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_system.replay.line_of_sight import STRAIGHT_PATH_TOLERANCE, LineOfSight, catch_up_speed
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from utils.math_utils import heading_diff

_MIN_LEG_M = 1e-6  # legs shorter than this (a vessel at rest) take the course of the reference state
# Critically damped line of sight with integral (damping sqrt(factor) / 2, line_of_sight.py), not the
# replay follower's 0.71: the autopilot's heading lag takes the rest, and at 2 the 5 m hull still
# swung 1.5 m across its path 20 s after a turn (WP6). The Gazebo odometry has no heading bias to
# correct, only drift in wind or current.
INTEGRAL_FACTOR = 4.0


class LosWaypointFollower:
    def __init__(
        self,
        vessel: ConcreteVessel,
        reference_states: Sequence[ActorState],
        reference_time_step: float,
        *,
        lookahead_s: float = 5.0,
        catch_up_s: float = 10.0,
        integral_factor: Optional[float] = INTEGRAL_FACTOR,
    ):
        if len(reference_states) < 2:
            raise ValueError(f"Vessel {vessel.id} needs at least two reference states for a waypoint mission")
        if reference_time_step <= 0:
            raise ValueError(f"reference_time_step must be positive, got {reference_time_step}")
        self.vessel = vessel
        self.participant_id = f"replay/{vessel.id}"
        self.catch_up_s = catch_up_s
        self.line_of_sight = LineOfSight(vessel, lookahead_s, integral_factor)
        self._reference = tuple(reference_states)
        self._time_step = float(reference_time_step)
        self._x = np.array([float(state.x) for state in reference_states])
        self._y = np.array([float(state.y) for state in reference_states])
        legs = np.hypot(np.diff(self._x), np.diff(self._y))
        self._arc = np.concatenate([[0.0], np.cumsum(legs)])  # path length at every waypoint
        self._courses = [
            math.atan2(self._y[index + 1] - self._y[index], self._x[index + 1] - self._x[index]) if legs[index] > _MIN_LEG_M else float(reference_states[index].heading) for index in range(len(legs))
        ]
        self._leg = 0

    def start(self, seed: int) -> None:
        del seed  # no randomness
        self._leg = 0
        self.line_of_sight.reset()

    @property
    def active_leg(self) -> int:
        return self._leg

    @property
    def cross_track_integral(self) -> float:
        return self.line_of_sight.integral

    def path_position(self, x: float, y: float):
        """Advance the active leg past every leg the point has passed; return (leg, cross-track error, path length at the projection)."""
        last_leg = len(self._courses) - 1
        while self._leg < last_leg:
            fraction = self._fraction(self._leg, x, y)
            if fraction < 1.0:
                break
            self._leg += 1
        leg = self._leg
        # Beyond the last waypoint the last leg is extended, so the path length keeps growing.
        fraction = max(self._fraction(leg, x, y), 0.0)
        if leg < last_leg:
            fraction = min(fraction, 1.0)
        course = self._courses[leg]
        offset_x, offset_y = x - self._x[leg], y - self._y[leg]
        cross_track = -math.sin(course) * offset_x + math.cos(course) * offset_y
        leg_length = self._arc[leg + 1] - self._arc[leg]
        return leg, cross_track, self._arc[leg] + fraction * leg_length

    def reference_arc(self, time: float) -> float:
        """Path length the reference has covered at a simulated time, held at both ends."""
        position = time / self._time_step
        last = len(self._reference) - 1
        if position <= 0:
            return 0.0
        if position >= last:
            return float(self._arc[-1])
        index = int(math.floor(position))
        return float(self._arc[index] + (position - index) * (self._arc[index + 1] - self._arc[index]))

    def reference_speed(self, time: float) -> float:
        """Reference speed at a simulated time, interpolated and held at both ends."""
        position = time / self._time_step
        last = len(self._reference) - 1
        if position <= 0:
            return float(self._reference[0].speed)
        if position >= last:
            return float(self._reference[last].speed)
        index = int(math.floor(position))
        before, after = self._reference[index].speed, self._reference[index + 1].speed
        return float(before + (after - before) * (position - index))

    def path_point(self, arc: float):
        """(x, y, course) of the path at a path length; before the start and beyond the end the first and last legs are extended."""
        leg = int(np.clip(np.searchsorted(self._arc, arc, side="right") - 1, 0, len(self._courses) - 1))
        course = self._courses[leg]
        along = arc - self._arc[leg]
        return self._x[leg] + along * math.cos(course), self._y[leg] + along * math.sin(course), course

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        own = observation.own_state
        x, y = float(own.x), float(own.y)
        leg, cross_track, arc = self.path_position(x, y)
        speed = self.reference_speed(request.time)
        target_x, target_y, course = self.path_point(arc + self.line_of_sight.lookahead(speed, cross_track))
        straight = abs(heading_diff(course, self._courses[leg])) <= STRAIGHT_PATH_TOLERANCE
        self.line_of_sight.step(cross_track, speed, request.target_time - request.time, straight)
        integral = self.line_of_sight.integral  # positive: the vessel has kept to port of the path, so aim to starboard of it
        heading = math.atan2(target_y - integral * math.cos(course) - y, target_x + integral * math.sin(course) - x)
        behind = self.reference_arc(request.time) - arc
        speed = float(np.clip(self.reference_speed(request.target_time) + catch_up_speed(behind, self.catch_up_s, self.vessel.max_acceleration), 0.0, self.vessel.max_speed))
        return HeadingSpeedCommand(heading=float(heading), speed=speed)

    def _fraction(self, leg: int, x: float, y: float) -> float:
        dx, dy = self._x[leg + 1] - self._x[leg], self._y[leg + 1] - self._y[leg]
        length2 = dx * dx + dy * dy
        if length2 <= _MIN_LEG_M**2:
            return 1.0
        return ((x - self._x[leg]) * dx + (y - self._y[leg]) * dy) / length2
