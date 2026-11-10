"""Replay ASV system as a lockstep participant on the heading_speed_cmd port."""

import math
from typing import Optional, Sequence

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_system.replay.line_of_sight import STRAIGHT_PATH_TOLERANCE, LineOfSight, catch_up_speed
from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_STATE_FOLLOWER
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from utils.math_utils import heading_diff, rotate_heading


class ReplayFollower:
    """Tracks a generated trajectory with heading and speed commands, stepped only by the simulation clock.

    Every step it commands the reference heading and speed at the step's target time, corrected
    by the vessel's position error from the reference point at the step's time. The correction
    grows continuously with the error, with no switch between modes (before, a 1 m tolerance
    switched between the reference and pure pursuit, and repeats near the threshold took
    different branches, WP4 finding):

    - cross-track: line of sight toward the reference path, with an integral against a constant
      heading bias (line_of_sight.py) that runs only while the reference keeps its heading for
      lookahead_s ahead.
    - along-track: catch_up_s seconds to close the gap, but no faster than the vessel can stop
      closing it (line_of_sight.catch_up_speed), within 0 and the vessel's max speed.

    On the reference both errors are exactly zero and the command is the reference at the
    target time, so a trajectory generated with the same kinematics is reproduced bit for bit.
    """

    spec = REPLAY_STATE_FOLLOWER

    def __init__(
        self,
        vessel: ConcreteVessel,
        reference_states: Sequence[ActorState],
        reference_time_step: float,
        *,
        lookahead_s: float = 5.0,
        catch_up_s: float = 10.0,
        integral_factor: Optional[float] = 2.0,
    ):
        if not reference_states:
            raise ValueError(f"Vessel {vessel.id} has an empty reference trajectory")
        if reference_time_step <= 0:
            raise ValueError(f"reference_time_step must be positive, got {reference_time_step}")
        self.vessel = vessel
        self.participant_id = f"replay/{vessel.id}"
        self.catch_up_s = catch_up_s
        self.line_of_sight = LineOfSight(vessel, lookahead_s, integral_factor)
        self._reference = tuple(reference_states)
        self._reference_time_step = float(reference_time_step)

    def start(self, seed: int) -> None:
        del seed  # the follower has no randomness
        self.line_of_sight.reset()

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        own = observation.own_state
        now = self.reference_state(request.time)
        target = self.reference_state(request.target_time)
        offset_x, offset_y = float(own.x - now.x), float(own.y - now.y)
        cos_heading, sin_heading = math.cos(now.heading), math.sin(now.heading)
        cross_track = -sin_heading * offset_x + cos_heading * offset_y  # positive: left of the reference
        along_track = cos_heading * offset_x + sin_heading * offset_y  # positive: ahead of it

        ahead = self.reference_state(request.time + self.line_of_sight.lookahead_s)
        straight = abs(heading_diff(ahead.heading, now.heading)) <= STRAIGHT_PATH_TOLERANCE
        correction = self.line_of_sight.correction(cross_track, float(now.speed), request.target_time - request.time, straight)
        heading = target.heading if correction == 0.0 else rotate_heading(target.heading, correction)
        speed = target.speed
        if along_track != 0.0:
            speed = float(np.clip(target.speed + catch_up_speed(-along_track, self.catch_up_s, self.vessel.max_acceleration), 0.0, max(self.vessel.max_speed, target.speed)))
        return HeadingSpeedCommand(heading=float(heading), speed=float(speed))

    @property
    def cross_track_integral(self) -> float:
        return self.line_of_sight.integral

    def reference_state(self, time: float) -> ActorState:
        """Reference state at a simulated time, interpolated between samples and held at both ends."""
        last = len(self._reference) - 1
        position = time / self._reference_time_step
        if position <= 0:
            return self._reference[0]
        if position >= last:
            return self._reference[last]
        index = int(math.floor(position))
        fraction = position - index
        before = self._reference[index]
        if fraction == 0.0:
            return before
        after = self._reference[index + 1]
        return ActorState(
            x=before.x + (after.x - before.x) * fraction,
            y=before.y + (after.y - before.y) * fraction,
            speed=before.speed + (after.speed - before.speed) * fraction,
            heading=rotate_heading(before.heading, heading_diff(after.heading, before.heading) * fraction),
        )
