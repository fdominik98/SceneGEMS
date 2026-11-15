"""Heading and speed autopilot of the custom control layer for the generated hull, whatever its steering type.

The class and the file keep the name of the twin differential-thrust hull they were written for;
the autopilot now drives a skid steered hull, a hull with a rudder and one with vectored thrust.

Two loops ask for a surge force and a yaw moment:

- surge: the speed reference moves toward the commanded speed at the vessel's max acceleration,
  as the kinematic layer does. Feedforward is the hull's surge damping at the reference and its
  inertia times the reference's acceleration, so the hull follows the reference without integral
  action. A PI term removes what the model misses.
- yaw: the heading error sets a turn rate demand within the vessel's max turn rate. The demand
  is linear near the heading and a square root farther out, so the hull can stop turning at the
  commanded heading with half its yaw deceleration. A rate loop turns the demand into a moment:
  yaw damping and inertia feedforward plus PI.

The allocator of the hull's steering type (actuator_allocation.py) turns the force and the moment
into the actuator command: the port and starboard thrusts of a skid steered hull, or the thrust
and the helm angle of a hull with a rudder or vectored thrust. Yaw has priority in each of them.
An integrator holds while its loop does not get what it asks for and its error would push the
demand further from what it gets (conditional integration), which is the anti-windup.

The gains come from the vessel model (AutopilotGains.from_dynamics). Each PI loop is placed as a
critically damped second-order loop on the hull's first-order surge or yaw dynamics, linearized
at half the max speed and at the max turn rate. Its natural frequency is BANDWIDTH times the
hull's own rate, c / m, but at most DISCRETE_LIMIT over the control step. The heading loop is
HEADING_SEPARATION times slower than the rate loop.

A helm brings what a pair of thrusters does not have, and the yaw loop of a hull with a rudder
or vectored thrust allows for it (a skid steered hull is controlled as before):

- The helm takes time to travel. The turn rate loop is HELM_SEPARATION times slower than the
  helm goes from amidships to hard over, so its proportional action does not ask the helm to move
  faster than it does. And the turn rate demand builds up at the yaw acceleration the heading
  approach plans with instead of jumping, as the speed reference does.
- A rudder's force follows the speed squared. The yaw acceleration planned with follows it
  (yaw_authority), so a slow hull approaches its heading more gently.
- A rudder is a fin in the flow at the stern: the hull's drift and turn rate change its angle of
  attack. The rudder's allocator takes that flow from the observed sway and turn rate, so the loop
  sees the hull's own yaw damping only.
- A vectored thruster's side force changes sides with the helm and with the thrust's direction.
  The autopilot follows where the helm is and holds the thrust back while it crosses over
  (actuator_allocation.wait_for_helm).
"""

import math
from dataclasses import dataclass
from typing import Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.control_layers.custom.actuator_allocation import ActuatorCommand, allocate_rudder, allocate_skid, allocate_vectored_thrust, helm_travel, wait_for_helm
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import rudder_normal_force_coefficient
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics
from utils.math_utils import heading_diff

BANDWIDTH = 4.0  # closed-loop natural frequency of the surge and turn rate loops, times the hull's own c / m
DISCRETE_LIMIT = 0.3  # and at most this over the control step, so the sampled loop stays close to the continuous design
HEADING_SEPARATION = 2.0  # the heading loop is this many times slower than the turn rate loop
YAW_DECELERATION_SHARE = 0.5  # share of the yaw deceleration of the steering's full moment the heading approach plans with
SURGE_DESIGN_SPEED_SHARE = 0.5  # the surge loop is linearized at this share of the max speed
RUDDER_SPEED_FLOOR_SHARE = 0.1  # below this share of the max speed a rudder counts as having the flow of that speed
HELM_SEPARATION = 2.0  # the turn rate loop is this many times slower than the helm travels from amidships to hard over


@dataclass(frozen=True)
class AutopilotGains:
    """Everything the autopilot knows of its hull. It travels to the controller container as a plain dict, so every field is a number or a string."""

    max_thrust: float  # N per thruster, both ways
    thruster_arm: float  # m, lateral offset of each of two thrusters; 0 for one
    surge_mass: float  # kg, rigid body and added mass
    surge_linear: float  # |xU|
    surge_quadratic: float  # |xUabsU|
    yaw_inertia: float  # kg m^2, rigid body and added inertia
    yaw_linear: float  # |nR|
    yaw_quadratic: float  # |nRabsR|
    speed_p: float  # N per m/s
    speed_i: float  # N per m
    rate_p: float  # N m per rad/s
    rate_i: float  # N m per rad
    heading_p: float  # rad/s per rad
    max_turn_rate: float  # rad/s
    max_acceleration: float  # m/s^2
    max_speed: float  # m/s
    # The steering gear. The defaults are those of a skid steered hull, which has no helm.
    steering_type: str = SteeringType.SKID.value
    steering_x: float = 0.0  # m, where the helm's side force acts (negative: aft)
    steering_max_angle: float = 0.0  # rad, hard over either way
    steering_rate: float = 0.0  # rad/s, helm speed
    steering_speed: float = 0.0  # m/s, the speed the helm's full moment is given at
    helm_yaw_moment: float = 0.0  # N m, the helm hard over at the steering speed and the thrust that holds it
    rudder_force_gain: float = 0.0  # N per (m/s)^2: one half rho times the rudder's area times its lift slope
    rudder_speed_floor: float = 0.0  # m/s, below it the rudder's flow counts as this speed

    @property
    def max_yaw_moment(self) -> float:
        """The steering's full moment: full differential thrust, or the helm hard over at the steering speed."""
        if self.steering_type == SteeringType.SKID.value:
            return 2.0 * self.max_thrust * self.thruster_arm
        return self.helm_yaw_moment

    @property
    def heading_deceleration(self) -> float:
        """rad/s^2 the heading approach plans with."""
        return YAW_DECELERATION_SHARE * self.max_yaw_moment / self.yaw_inertia

    @classmethod
    def from_dynamics(cls, dynamics: VesselDynamics, vessel: ConcreteVessel, control_dt: float) -> "AutopilotGains":
        surge_mass = dynamics.total_mass + abs(dynamics.xDotU)
        design_speed = SURGE_DESIGN_SPEED_SHARE * vessel.max_speed
        surge_slope = abs(dynamics.xU) + 2.0 * abs(dynamics.xUabsU) * design_speed
        yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)
        yaw_slope = abs(dynamics.nR) + 2.0 * abs(dynamics.nRabsR) * vessel.max_angular_speed
        speed_p, speed_i, _ = _critically_damped_pi(surge_mass, surge_slope, _loop_frequency(surge_mass, surge_slope, control_dt))
        skid = dynamics.steering_type == SteeringType.SKID.value
        if skid:
            rate_frequency = _loop_frequency(yaw_inertia, yaw_slope, control_dt)
        else:
            # A hull with a helm is also held back by its steering gear (a rudder is a fin at the stern), and the
            # calibration leaves a hull that cannot follow its helm next to no damping of its own: the loop is at
            # least as fast as on a hull whose damping holds the max turn rate against the helm's full moment.
            # And it is no faster than the helm can follow.
            helm_frequency = dynamics.steering_rate / (HELM_SEPARATION * dynamics.steering_max_angle)
            rate_frequency = min(_loop_frequency(yaw_inertia, max(yaw_slope, dynamics.max_yaw_moment / vessel.max_angular_speed), control_dt), helm_frequency)
        if skid or 2.0 * rate_frequency * yaw_inertia >= yaw_slope:
            rate_p, rate_i, rate_frequency = _critically_damped_pi(yaw_inertia, yaw_slope, rate_frequency)
        else:
            # The helm keeps the loop slower than half the hull's own rate c / m, where a double pole would
            # take a negative P. Without P, this I puts the slower pole of m s^2 + c s + I at the loop's frequency.
            rate_p, rate_i = 0.0, rate_frequency * (yaw_slope - rate_frequency * yaw_inertia)
        return cls(
            max_thrust=dynamics.max_thrust,
            thruster_arm=dynamics.thruster_y,
            surge_mass=surge_mass,
            surge_linear=abs(dynamics.xU),
            surge_quadratic=abs(dynamics.xUabsU),
            yaw_inertia=yaw_inertia,
            yaw_linear=abs(dynamics.nR),
            yaw_quadratic=abs(dynamics.nRabsR),
            speed_p=speed_p,
            speed_i=speed_i,
            rate_p=rate_p,
            rate_i=rate_i,
            heading_p=rate_frequency / HEADING_SEPARATION,
            max_turn_rate=vessel.max_angular_speed,
            max_acceleration=vessel.max_acceleration,
            max_speed=vessel.max_speed,
            steering_type=dynamics.steering_type,
            steering_x=dynamics.steering_x,
            steering_max_angle=dynamics.steering_max_angle,
            steering_rate=dynamics.steering_rate,
            steering_speed=dynamics.steering_speed,
            helm_yaw_moment=0.0 if skid else dynamics.max_yaw_moment,
            rudder_force_gain=-rudder_normal_force_coefficient(dynamics.rudder_area, dynamics.rudder_lift_slope),
            rudder_speed_floor=RUDDER_SPEED_FLOOR_SHARE * vessel.max_speed if dynamics.steering_type == SteeringType.RUDDER.value else 0.0,
        )


def _loop_frequency(mass: float, slope: float, control_dt: float) -> float:
    """BANDWIDTH times the hull's own rate, within what the control step allows."""
    return min(BANDWIDTH * slope / mass, DISCRETE_LIMIT / control_dt)


def _critically_damped_pi(mass: float, slope: float, frequency: float):
    """P and I placing m s^2 + (c + P) s + I at a double pole of that frequency, and the frequency."""
    return max(2.0 * frequency * mass - slope, 0.0), mass * frequency**2, frequency


@dataclass(frozen=True)
class HullObservation:
    heading: float  # rad, counterclockwise from east
    surge: float  # m/s, body x
    yaw_rate: float  # rad/s, counterclockwise
    sway: float = 0.0  # m/s, body y (to port); only a rudder's allocation reads it


def _pushes_further(error: float, wanted: float, given: float) -> bool:
    """Whether integrating this error would move the demand further from what the actuators give."""
    return wanted != given and math.copysign(1.0, error) == math.copysign(1.0, wanted - given)


class TwinThrustAutopilot:
    """The heading and speed autopilot of one hull; the allocation follows the gains' steering type."""

    def __init__(self, gains: AutopilotGains):
        self.gains = gains
        self.reset()

    def reset(self, speed: Optional[float] = None) -> None:
        """Clear the integrators. The speed reference starts at `speed`, or at the first observed surge speed when None."""
        self._speed_reference: Optional[float] = speed
        self._speed_integral = 0.0  # m
        self._rate_integral = 0.0  # rad
        self._previous_rate_demand: Optional[float] = None
        self._astern = False  # a vectored thruster running astern (actuator_allocation.allocate_vectored_thrust)
        self._helm_angle = 0.0  # rad, where a vectored thruster's helm is: it starts amidships and travels at the steering rate

    def yaw_authority(self, surge: float) -> float:
        """Share of the steering's full moment that is there at this surge speed: a rudder's force follows the speed squared."""
        g = self.gains
        if g.steering_type != SteeringType.RUDDER.value:
            return 1.0
        return min((max(abs(surge), g.rudder_speed_floor) / g.steering_speed) ** 2, 1.0)

    def turn_rate_demand(self, heading_error: float, authority: float = 1.0) -> float:
        """Linear near the heading, sqrt(2 a |e|) farther out (a the planned deceleration, with that share of the steering's moment), within the max turn rate."""
        g = self.gains
        gain, deceleration = g.heading_p, g.heading_deceleration * authority
        magnitude = abs(heading_error)
        linear_limit = deceleration / gain**2
        if magnitude <= linear_limit:
            demand = gain * magnitude
        else:
            demand = math.sqrt(2.0 * deceleration * (magnitude - linear_limit / 2.0))
        return math.copysign(min(demand, g.max_turn_rate), heading_error)

    def allocate(self, force: float, moment: float, observation: HullObservation, dt: float) -> ActuatorCommand:
        """The actuator command of the hull's steering type for a surge force and a yaw moment, held over the control step dt."""
        g = self.gains
        if g.steering_type == SteeringType.SKID.value:
            return allocate_skid(force, moment, max_thrust=g.max_thrust, thruster_arm=g.thruster_arm)
        if g.steering_type == SteeringType.RUDDER.value:
            return allocate_rudder(
                force,
                moment,
                observation.surge,
                observation.sway + g.steering_x * observation.yaw_rate,
                max_thrust=g.max_thrust,
                steering_x=g.steering_x,
                max_angle=g.steering_max_angle,
                force_gain=g.rudder_force_gain,
                speed_floor=g.rudder_speed_floor,
            )
        if g.steering_type == SteeringType.VECTORED_THRUST.value:
            command = allocate_vectored_thrust(force, moment, max_thrust=g.max_thrust, steering_x=g.steering_x, max_angle=g.steering_max_angle, astern=self._astern)
            self._astern = command.thrusts[0] < 0.0
            command = wait_for_helm(command, self._helm_angle, steering_x=g.steering_x, max_angle=g.steering_max_angle)
            self._helm_angle = helm_travel(self._helm_angle, command.helm_angle, g.steering_rate * dt)
            return command
        raise ValueError(f"no actuator allocation for steering type {g.steering_type!r}")

    def command(self, desired_heading: float, desired_speed: float, observation: HullObservation, dt: float) -> ActuatorCommand:
        g = self.gains
        target_speed = min(max(desired_speed, 0.0), g.max_speed)
        if self._speed_reference is None:
            self._speed_reference = observation.surge
        step = g.max_acceleration * dt
        previous_reference = self._speed_reference
        self._speed_reference = min(max(target_speed, previous_reference - step), previous_reference + step)
        speed_reference = self._speed_reference
        acceleration = (speed_reference - previous_reference) / dt

        authority = self.yaw_authority(observation.surge)
        rate_demand = self.turn_rate_demand(heading_diff(desired_heading, observation.heading), authority)
        if g.steering_type != SteeringType.SKID.value:
            # A helm takes time to come back from hard over, so the hull would overshoot a demand that jumps.
            # The demand builds up at the yaw acceleration the heading approach plans with, from the hull's
            # own turn rate at first. It falls freely: the approach already plans the deceleration.
            # A reversal drops the old turn at once and builds up the new one from zero.
            previous = observation.yaw_rate if self._previous_rate_demand is None else self._previous_rate_demand
            reach = (abs(previous) if previous * rate_demand > 0.0 else 0.0) + g.heading_deceleration * authority * dt
            rate_demand = math.copysign(min(abs(rate_demand), reach), rate_demand)
        rate_change = 0.0 if self._previous_rate_demand is None else (rate_demand - self._previous_rate_demand) / dt
        self._previous_rate_demand = rate_demand

        rate_error = rate_demand - observation.yaw_rate
        moment = damping(g.yaw_linear, g.yaw_quadratic, rate_demand) + g.yaw_inertia * rate_change + g.rate_p * rate_error + g.rate_i * self._rate_integral
        speed_error = speed_reference - observation.surge
        force = damping(g.surge_linear, g.surge_quadratic, speed_reference) + g.surge_mass * acceleration + g.speed_p * speed_error + g.speed_i * self._speed_integral

        command = self.allocate(force, moment, observation, dt)

        # Conditional integration: hold an integrator that would push further into its limit.
        if not _pushes_further(rate_error, moment, command.moment):
            self._rate_integral += rate_error * dt
        if not _pushes_further(speed_error, force, command.force):
            self._speed_integral += speed_error * dt
        return command
