"""Line-of-sight cross-track correction shared by the replay followers (replay_follower.py and the custom
controller's control_layers/custom/los_waypoint_follower.py), and their along-track catch-up.

The correction to the path's course is -atan((e + i) / lookahead), e the cross-track error
(positive to port of the path) and i its integral:

- lookahead: lookahead_s of travel at the path's speed, at least one vessel length, and for a
  large error at least TURN_LIMITED_LOOKAHEAD * sqrt(R |e|), R = speed / max turn rate the
  vessel's turning radius. Near the path the heading demand then changes at about speed * e /
  lookahead^2, which this keeps at a quarter of the max turn rate. A fixed lookahead made the
  100 m hull (R about 1 km at 8 m/s) overshoot after a turn and oscillate (WP3).
- integral: time integral_factor times the line of sight's own time constant lookahead / speed,
  so the damping is the same at every scale (0.71 for a factor of 2). It corrects at most
  MAX_BIAS_CORRECTION of a constant heading bias (ArduPilot's EKF heading on SITL's motorboat is
  biased by up to about 2 degrees, WP3), and integrates only while the error is one such a bias
  can cause: no larger than the integral's own limit, with the lookahead not stretched, and only
  where the path ahead is straight (the follower tells, within STRAIGHT_PATH_TOLERANCE). A turn,
  and the error a turn leaves, then do not wind it up: on the Gazebo hulls they did, and the
  5 m hull swung across the path for more than 20 s after each turn while the 100 m hull held
  3 m off it (WP6).

On the path with no integral the correction is exactly 0.

The along-track catch-up closes a gap in catch_up_s, but no faster than the vessel can stop
closing it at its max acceleration: sqrt(a |gap|), the speed from which it brakes to the
reference speed within the gap at a / 2. The 100 m hull (0.05 m/s^2) otherwise came out of a
turn 3 m/s fast and overshot its reference by 160 m (WP6).
"""

import math
from typing import Optional

from concrete_level.models.concrete_actors import ConcreteVessel

TURN_LIMITED_LOOKAHEAD = 2.0
MAX_BIAS_CORRECTION = math.radians(15.0)
STRAIGHT_PATH_TOLERANCE = math.radians(0.5)  # course change over the lookahead below which the path counts as straight


def catch_up_speed(gap: float, catch_up_s: float, max_acceleration: float) -> float:
    """Speed to add to the reference speed for a vessel gap meters behind its reference (negative: ahead)."""
    closing = abs(gap) / catch_up_s
    if max_acceleration > 0:
        closing = min(closing, math.sqrt(max_acceleration * abs(gap)))
    return math.copysign(closing, gap)


class LineOfSight:
    def __init__(self, vessel: ConcreteVessel, lookahead_s: float, integral_factor: Optional[float]):
        self.vessel = vessel
        self.lookahead_s = lookahead_s
        self.integral_factor = integral_factor  # None: no integral term
        self.integral = 0.0  # meters

    def reset(self) -> None:
        self.integral = 0.0

    def base_lookahead(self, speed: float) -> float:
        return max(self.vessel.length, self.lookahead_s * speed)

    def lookahead(self, speed: float, cross_track: float) -> float:
        base = self.base_lookahead(speed)
        if self.vessel.max_angular_speed <= 0 or speed <= 0:
            return base
        turning_radius = speed / self.vessel.max_angular_speed
        return max(base, TURN_LIMITED_LOOKAHEAD * math.sqrt(turning_radius * abs(cross_track)))

    def step(self, cross_track: float, speed: float, dt: float, straight: bool = True) -> float:
        """Update the integral for one step of dt at the path's speed; return the lookahead (m). straight: the path ahead is straight."""
        base = self.base_lookahead(speed)
        lookahead = self.lookahead(speed, cross_track)
        limit = base * math.tan(MAX_BIAS_CORRECTION)
        if self.integral_factor is not None and straight and speed > 0 and lookahead == base and abs(cross_track) <= limit:
            increment = cross_track * dt * speed / (self.integral_factor * base)
            self.integral = min(max(self.integral + increment, -limit), limit)
        return lookahead

    def correction(self, cross_track: float, speed: float, dt: float, straight: bool = True) -> float:
        """Heading correction (rad) for one step of dt at the path's speed; updates the integral."""
        lookahead = self.step(cross_track, speed, dt, straight)
        return -math.atan2(cross_track + self.integral, lookahead)
