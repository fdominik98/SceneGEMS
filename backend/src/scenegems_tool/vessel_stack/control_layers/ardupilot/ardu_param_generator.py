"""ArduPilot Rover parameters of one vessel: limits from the vessel, steering and speed control from the plant it drives.

The navigation limits (turn rate, speed, acceleration) are the vessel's. The steering and speed
controllers are derived from the yaw and surge dynamics of the simulation layer's plant, so
that the feedforward alone gives the commanded turn rate and speed and the PI terms only remove
what the linear feedforward misses. The outputs and the plant follow the vessel's steering type:

- gazebo: the generated hull (simulation_layers/gazebo/generators/vessel_dynamics.py).
  - skid: ThrottleLeft drives the port thruster, ThrottleRight the starboard one, so steering is
    differential thrust and throttle the common thrust.
  - rudder: GroundSteering on servo 1 is the helm angle, Throttle on servo 3 the one thruster.
    The rudder's force grows with the square of the speed, and Rover scales its steering down
    with the speed above MOT_SPD_SCA_BASE, which is set to the speed from which the rudder
    holds the vessel's max turn rate.
  - vectored_thrust: the same two outputs with Rover's vectored thrust (MOT_VEC_ANGLEMAX, the
    helm's hard over angle): Rover turns its steering into the thruster's angle and raises the
    throttle, so the steering is the side thrust as a share of the full thrust.
- ardupilot_sim: SITL's boat (libraries/SITL/SIM_Sailboat.cpp and SIM_MotorBoat.h at the pinned
  commit): a 1.8 m turning circle at 35 degrees of rudder, 50 N of thrust per unit throttle
  against 0.5 v^2 of hull drag on 2 kg (10 m/s at full throttle) and no yaw inertia. Its size
  does not follow the vessel; the parameters cap it at the vessel's limits.
  - rudder: frame motorboat, one rudder on servo 1 and one throttle on servo 3.
  - skid: frame motorboat-skid (any frame name with "skid" in it), the left motor on servo 1
    and the right one on servo 3; their difference is the boat's rudder, their mean its throttle.
  - vectored_thrust: SITL's boat has none, so the resolver refuses the vessel and
    control_parameters raises.
  The outputs must match the frame: skid outputs on the frame motorboat made SITL read the left
  motor as its rudder, so the boat crept while ArduPilot held its heading at rest (WP3 finding).

A plant of the gazebo layer is the hull the vessel model generator would write for this vessel
and environment; a vessel with its own SDF (VesselConfig.gazebo_vessel_model) gets the gains of
the generated hull.

Rover GUIDED clamps a heading and speed target to WP_SPEED, so a vessel driven by GUIDED targets
gets the vessel's max speed there. Before, WP_SPEED was the trajectory's cruise speed and the
replay follower could not catch up after the start (it trailed by about 11 m, WP3 finding).
ArduAgent missions keep the cruise speed, since WP_SPEED is their mission speed.

Rover facts used here, read at the pinned commit (deploy/images/upstream_pins.env):

- AR_AttitudeControl::get_steering_out_rate: steering = ATC_STR_RAT_FF * turn rate plus the PID,
  not limited to 1; the integrator only shrinks while a steering limit flag is set.
- AP_MotorsUGV::output_regular (GroundSteering and Throttle): above MOT_SPD_SCA_BASE (1 m/s by
  default) the steering is multiplied by base / speed, and only then limited to full deflection;
  at or below it both steering limit flags are set, so the integrator rests. With
  MOT_VEC_ANGLEMAX above zero it is instead limited to throttle * tan(angle max), turned into
  the angle atan(steering / throttle) as a share of the angle max, and the throttle is divided
  by the cosine of that angle; there is no speed scaling then.
- AP_MotorsUGV::output_skid_steering: left = throttle + steering, right = throttle - steering,
  without speed scaling. Skid steering is on when ThrottleLeft and ThrottleRight are assigned.
"""

import math
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import damping_force
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics, derive_vessel_dynamics

GRAVITY = 9.81
SERVO_GROUND_STEERING = 26
SERVO_THROTTLE = 70
SERVO_THROTTLE_LEFT = 73
SERVO_THROTTLE_RIGHT = 74
CRUISE_THROTTLE_RANGE = (5.0, 100.0)  # percent; Rover ignores its speed nudge outside this range

# SITL's boat (SIM_Sailboat.cpp with a motor, pinned ArduPilot commit).
SITL_RUDDER_FRAME = "motorboat"
SITL_SKID_FRAME = "motorboat-skid"  # "skid" in the frame name makes SITL steer by its two motors
GAZEBO_SITL_FRAME = "motorboat"  # the physics come from Gazebo (JSON backend); the frame only names the default parameters
SITL_TURNING_CIRCLE_M = 1.8
SITL_RUDDER_ANGLE_MAX_DEG = 35.0
SITL_THRUST_PER_THROTTLE_N = 50.0
SITL_HULL_DRAG_COEFFICIENT = 0.5  # N per (m/s)^2
SITL_BOAT_MASS_KG = 2.0
SITL_TOP_SPEED = math.sqrt(SITL_THRUST_PER_THROTTLE_N / SITL_HULL_DRAG_COEFFICIENT)
SITL_SKID_RUDDER_PER_STEERING = 2.0  # the skid boat's rudder is the left motor minus the right one: twice Rover's steering
SITL_SKID_PIVOT_RATE = math.radians(5.0 * math.pi)  # rad/s per unit of rudder of the skid boat at rest (5 pi deg/s)
MOTOR_SPEED_SCALE_BASE = 1.0  # Rover's default MOT_SPD_SCA_BASE: above this speed Rover scales rudder steering by base / speed

# Closed-loop shaping, the same for every plant.
RATE_LOOP_SPEEDUP = 2.0  # the turn rate loop settles this many times faster than the open-loop hull
HEADING_LOOP_SEPARATION = 2.0  # the heading loop is this many times slower than the turn rate loop
SPEED_LOOP_SPEEDUP = 2.0
YAW_ACCEL_SHARE = 1.0  # share of the hull's yaw acceleration at full steering the controller may ask for
# A helm that travels: the turn rate loop's gain stays below hull time constant / (this * helm travel time),
# which keeps the loop of hull, PI controller and helm (as a first order lag) at a damping ratio of 0.7 or more.
HELM_LAG_GAIN_LIMIT = 2.0
# A rudder's gains are those of at least this share of the speed from which it holds the max turn
# rate: slower than that it steers little, and gains that grow further only slam the helm.
RUDDER_LOW_SPEED_SHARE = 0.5
RUDDER_GAIN_STEP = 0.05  # relative step of turn rate and rudder angle the rudder hull is linearized over
_SEARCH_ITERATIONS = 40


@dataclass(frozen=True)
class ControlParameters:
    """What the plant decides: outputs, feedforwards, PI gains and the speeds of the plant."""

    servo1_function: int
    servo3_function: int
    skid_steering: bool
    turn_rate_ff: float  # steering per rad/s of turn rate at the vessel's max turn rate
    turn_rate_p: float
    turn_rate_i: float
    heading_p: float  # rad/s of turn rate per rad of heading error
    turn_accel_max_deg: float  # deg/s^2 of turn rate change; 0 leaves Rover's default
    cruise_throttle_percent: float
    speed_p: float
    speed_i: float
    top_speed: float  # m/s at full throttle
    extra: Tuple[Tuple[str, float], ...] = ()  # further Rover parameters of this plant (MOT_SPD_SCA_BASE, MOT_VEC_ANGLEMAX)

    def as_params(self) -> dict:
        return {
            "SERVO1_FUNCTION": self.servo1_function,
            "SERVO3_FUNCTION": self.servo3_function,
            "SKID_STEER_OUT": 1 if self.skid_steering else 0,
            "ATC_STR_RAT_FF": self.turn_rate_ff,
            "ATC_STR_RAT_P": self.turn_rate_p,
            "ATC_STR_RAT_I": self.turn_rate_i,
            "ATC_STR_RAT_D": 0.0,
            "ATC_STR_ANG_P": self.heading_p,
            "ATC_SPEED_P": self.speed_p,
            "ATC_SPEED_I": self.speed_i,
            "ATC_SPEED_D": 0.0,
            "CRUISE_THROTTLE": self.cruise_throttle_percent,
            **dict(self.extra),
        }


def steering_outputs(steering_type: SteeringType) -> Tuple[int, int, bool]:
    """(SERVO1_FUNCTION, SERVO3_FUNCTION, skid steering) of a steering type: two motors, or a helm and a motor."""
    if steering_type == SteeringType.SKID:
        return SERVO_THROTTLE_LEFT, SERVO_THROTTLE_RIGHT, True
    return SERVO_GROUND_STEERING, SERVO_THROTTLE, False


def _unsupported(vessel_id: object, steering_type: SteeringType, simulation_layer: SimulationLayerId) -> ValueError:
    if simulation_layer == SimulationLayerId.ARDUPILOT_SIM:
        steering = steering_type.value.replace("_", " ")
        return ValueError(f"vessel {vessel_id} has {steering} steering, which the ardupilot_sim simulation layer does not simulate: SITL's boat steers by a rudder or by two motors")
    return ValueError(f"ArduPilot does not drive the {simulation_layer.value} simulation layer")


def sitl_frame(steering_type: SteeringType, simulation_layer: SimulationLayerId, vessel_id: object = "") -> str:
    """The SITL frame (sim_vehicle.py -f) of a vessel: on ardupilot_sim it selects how SITL's boat steers, so it must match the outputs."""
    if simulation_layer == SimulationLayerId.GAZEBO:
        return GAZEBO_SITL_FRAME
    if simulation_layer == SimulationLayerId.ARDUPILOT_SIM and steering_type == SteeringType.RUDDER:
        return SITL_RUDDER_FRAME
    if simulation_layer == SimulationLayerId.ARDUPILOT_SIM and steering_type == SteeringType.SKID:
        return SITL_SKID_FRAME
    raise _unsupported(vessel_id, steering_type, simulation_layer)


def _cruise_throttle(throttle_fraction: float) -> float:
    return float(np.clip(100.0 * throttle_fraction, *CRUISE_THROTTLE_RANGE))


def _surge_loop(dynamics: VesselDynamics, cruise_speed: float) -> Tuple[float, float, float]:
    """(cruise throttle percent, speed P, speed I) of a generated hull.

    Throttle t gives t times the total thrust against |xU| u + |xUabsU| u^2. Linearized at the
    cruise speed the hull is first order; the PI zero cancels its pole and the loop settles
    SPEED_LOOP_SPEEDUP times faster. A rudder's own drag and the thrust a vectored thruster
    spends sideways are left to the PI terms.
    """
    thrust = dynamics.total_thrust
    cruise = min(cruise_speed, dynamics.design_speed)
    surge_damping = abs(dynamics.xU) * cruise + abs(dynamics.xUabsU) * cruise**2
    surge_slope = abs(dynamics.xU) + 2.0 * abs(dynamics.xUabsU) * cruise
    surge_mass = dynamics.total_mass + abs(dynamics.xDotU)
    speed_p = (SPEED_LOOP_SPEEDUP - 1.0) * surge_slope / thrust
    speed_i = speed_p * surge_slope / surge_mass
    return _cruise_throttle(surge_damping / thrust), speed_p, speed_i


def gazebo_control_parameters(dynamics: VesselDynamics, max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of the generated twin-thrust hull (skid steering).

    Yaw: steering s gives a moment of 2 s T y (T the max thrust per thruster, y its lateral arm),
    which the hull's yaw damping |nR| r + |nRabsR| r^2 balances at a steady turn rate r. The
    feedforward is the steering of the vessel's max turn rate over that rate. Linearized there,
    the hull is first order with gain 2 T y / c and time constant (Izz - nDotR) / c, c the damping
    slope; the PI zero cancels that pole and the loop settles RATE_LOOP_SPEEDUP times faster.
    Surge: throttle t gives 2 t T against |xU| u + |xUabsU| u^2, the same way.
    """
    arm_moment = 2.0 * dynamics.max_thrust * dynamics.thruster_y
    yaw_damping = abs(dynamics.nR) * max_turn_rate + abs(dynamics.nRabsR) * max_turn_rate**2
    turn_rate_ff = yaw_damping / arm_moment / max_turn_rate
    yaw_slope = abs(dynamics.nR) + 2.0 * abs(dynamics.nRabsR) * max_turn_rate
    yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)
    yaw_time_constant = yaw_inertia / yaw_slope
    yaw_gain = arm_moment / yaw_slope  # rad/s of steady turn rate per unit steering, at the max turn rate
    turn_rate_p = (RATE_LOOP_SPEEDUP - 1.0) / yaw_gain
    rate_loop_time_constant = yaw_time_constant / RATE_LOOP_SPEEDUP
    heading_p = 1.0 / (HEADING_LOOP_SEPARATION * rate_loop_time_constant)
    turn_accel_max = YAW_ACCEL_SHARE * arm_moment / yaw_inertia

    cruise_throttle_percent, speed_p, speed_i = _surge_loop(dynamics, cruise_speed)
    return ControlParameters(
        servo1_function=SERVO_THROTTLE_LEFT,
        servo3_function=SERVO_THROTTLE_RIGHT,
        skid_steering=True,
        turn_rate_ff=turn_rate_ff,
        turn_rate_p=turn_rate_p,
        turn_rate_i=turn_rate_p / yaw_time_constant,
        heading_p=heading_p,
        turn_accel_max_deg=math.degrees(turn_accel_max),
        cruise_throttle_percent=cruise_throttle_percent,
        speed_p=speed_p,
        speed_i=speed_i,
        top_speed=dynamics.design_speed,
    )


def _largest(function: Callable[[float], float], low: float, high: float) -> float:
    """Argument of the largest value of a function with one peak between low and high."""
    for _ in range(_SEARCH_ITERATIONS):
        first, second = low + (high - low) / 3.0, high - (high - low) / 3.0
        if function(first) < function(second):
            low = first
        else:
            high = second
    return (low + high) / 2.0


def _last_true(holds: Callable[[float], bool], low: float, high: float) -> float:
    """Largest argument for which holds is true, when it is true at low and false at high."""
    for _ in range(_SEARCH_ITERATIONS):
        middle = (low + high) / 2.0
        if holds(middle):
            low = middle
        else:
            high = middle
    return low


def _rudder_turn_flow(dynamics: VesselDynamics, turn_rate: float, speed: float) -> Tuple[float, float]:
    """(side force in N the rudder must give, the rudder's sway through the water in m/s) of a steady turn to port.

    The hull slides to starboard until its sway damping balances the centripetal force and the
    rudder's side force, and the stern swings to starboard as well.
    """
    side_force = damping_force(dynamics.nR, dynamics.nRabsR, turn_rate) / abs(dynamics.steering_x)
    outward_force = dynamics.total_mass * speed * turn_rate + side_force
    linear, quadratic = abs(dynamics.yV), abs(dynamics.yVabsV)
    slide = (-linear + math.sqrt(linear**2 + 4.0 * quadratic * outward_force)) / (2.0 * quadratic) if quadratic > 0 else outward_force / linear
    return side_force, -(slide + abs(dynamics.steering_x) * turn_rate)


def _rudder_turning_force(dynamics: VesselDynamics, angle: float, speed: float, sway_at_rudder: float) -> float:
    """Side force (N) that turns the vessel to port, of the rudder `angle` rad over to port (a negative helm angle)."""
    return -dynamics.helm_force(-angle, speed, sway_at_rudder, 0.0)[1]


def rudder_turn_share(dynamics: VesselDynamics, turn_rate: float, speed: float) -> Optional[float]:
    """Share of the rudder's hard over angle that holds a steady turn at turn_rate (rad/s) at a surge of speed (m/s).

    None when the rudder does not hold that turn at that speed. The turn is the one the hull's
    yaw damping was calibrated on (steady_turn in vessel_dynamics.py), with the surge held
    instead of the thrust, as Rover's speed controller does:

    - yaw: the rudder's side force at its lever arm balances the yaw damping |nR| r + |nRabsR| r^2;
    - sway: the hull slides outward until its sway damping balances that side force and the
      centripetal force m u r;
    - the rudder meets the water at its own velocity, the hull's sway plus the stern's swing, so
      the slide eases its angle of attack. A turn takes about twice the rudder angle a straight
      course at the same speed would suggest.
    """
    side_force, sway_at_rudder = _rudder_turn_flow(dynamics, turn_rate, speed)

    def turning_force(angle: float) -> float:
        return _rudder_turning_force(dynamics, angle, speed, sway_at_rudder)

    # The force peaks near 35 degrees of angle of attack; a rudder that goes further gains nothing there.
    best_angle = _largest(turning_force, 0.0, dynamics.steering_max_angle)
    if turning_force(best_angle) < side_force:
        return None
    low, high = 0.0, best_angle
    for _ in range(_SEARCH_ITERATIONS):
        middle = (low + high) / 2.0
        if turning_force(middle) < side_force:
            low = middle
        else:
            high = middle
    return high / dynamics.steering_max_angle


def rudder_authority_speed(dynamics: VesselDynamics, turn_rate: float) -> float:
    """Lowest speed (m/s) at which the rudder hard over holds turn_rate; the hull's full thrust speed when it never does."""
    if rudder_turn_share(dynamics, turn_rate, dynamics.design_speed) is None:
        return dynamics.design_speed
    return dynamics.design_speed - _last_true(lambda below: rudder_turn_share(dynamics, turn_rate, dynamics.design_speed - below) is not None, 0.0, dynamics.design_speed)


def steering_share_of_rudder(speed: float, speed_scale_base: float) -> float:
    """Share of hard over that Rover's full steering puts the rudder at: base / speed above MOT_SPD_SCA_BASE, else all of it."""
    return min(1.0, speed_scale_base / speed) if speed_scale_base > 0 and speed > 0 else 1.0


def rover_rudder_steering(rudder_share: float, speed: float, speed_scale_base: float) -> float:
    """Rover steering that puts the rudder at rudder_share of hard over at speed, with Rover's speed scaling undone."""
    return rudder_share / steering_share_of_rudder(speed, speed_scale_base)


@dataclass(frozen=True)
class HelmTurn:
    """A steady turn of a generated hull with a helm, and how the hull answers the steering around it."""

    turn_rate: float  # rad/s
    steering: float  # Rover steering that holds it
    yaw_gain: float  # rad/s more of steady turn rate per unit more of steering
    moment_per_steering: float  # N m of yaw moment per unit more of steering, before the turn rate follows
    full_moment: float  # N m the largest steering the outputs take gives
    helm_time: float  # s the helm travels to the angle of this turn


def _helm_control_parameters(dynamics: VesselDynamics, turn: HelmTurn, cruise_speed: float, extra: Tuple[Tuple[str, float], ...]) -> ControlParameters:
    """Gains of a generated hull with a helm, linearized at a steady turn.

    The feedforward is the turn's steering over its turn rate. Around the turn the hull is first
    order: more steering gives its moment at once and settles at the yaw gain, so the time
    constant is inertia * yaw gain / moment per steering, and the loop is shaped as for the
    twin-thrust hull. The helm travels at its own speed, which the linear loop does not know:
    the loop gain is limited so that hull, PI controller and helm stay well damped
    (HELM_LAG_GAIN_LIMIT), the heading loop waits for the helm too, and the turn rate is not
    asked to change faster than the helm reaches the angle of the turn.
    """
    turn_rate, steering, yaw_gain, helm_time = turn.turn_rate, turn.steering, turn.yaw_gain, turn.helm_time
    yaw_time_constant = dynamics.yaw_inertia * yaw_gain / turn.moment_per_steering
    loop_gain = RATE_LOOP_SPEEDUP - 1.0
    if helm_time > 0:
        loop_gain = min(loop_gain, yaw_time_constant / (HELM_LAG_GAIN_LIMIT * helm_time))
    turn_rate_p = loop_gain / yaw_gain
    rate_loop_time_constant = yaw_time_constant / (1.0 + loop_gain) + helm_time
    turn_accel_max = YAW_ACCEL_SHARE * turn.full_moment / dynamics.yaw_inertia
    if helm_time > 0:
        turn_accel_max = min(turn_accel_max, turn_rate / helm_time)
    cruise_throttle_percent, speed_p, speed_i = _surge_loop(dynamics, cruise_speed)
    return ControlParameters(
        servo1_function=SERVO_GROUND_STEERING,
        servo3_function=SERVO_THROTTLE,
        skid_steering=False,
        turn_rate_ff=steering / turn_rate,
        turn_rate_p=turn_rate_p,
        turn_rate_i=turn_rate_p / yaw_time_constant,
        heading_p=1.0 / (HEADING_LOOP_SEPARATION * rate_loop_time_constant),
        turn_accel_max_deg=math.degrees(turn_accel_max),
        cruise_throttle_percent=cruise_throttle_percent,
        speed_p=speed_p,
        speed_i=speed_i,
        top_speed=dynamics.design_speed,
        extra=extra,
    )


def rudder_reference_turn(dynamics: VesselDynamics, max_turn_rate: float, cruise_speed: float) -> Tuple[float, float, float, float]:
    """(speed scale base, speed, turn rate, rudder share) of the turn the rudder hull's gains are derived at.

    The speed scale base (MOT_SPD_SCA_BASE) is the speed from which the rudder hard over holds the
    vessel's max turn rate. The turn is at the cruise speed (at least RUDDER_LOW_SPEED_SHARE of
    the base) and at the max turn rate, or at the turn rate the rudder hard over holds there
    when that is less.
    """
    base = rudder_authority_speed(dynamics, max_turn_rate)
    speed = max(min(cruise_speed, dynamics.design_speed), RUDDER_LOW_SPEED_SHARE * base)
    turn_rate = max_turn_rate
    if rudder_turn_share(dynamics, turn_rate, speed) is None:
        turn_rate = _last_true(lambda rate: rate == 0.0 or rudder_turn_share(dynamics, rate, speed) is not None, 0.0, max_turn_rate)
        turn_rate = max(turn_rate, 1e-3 * max_turn_rate)  # a rudder that holds no turn at all: the gains of hard over for the smallest turn
    share = rudder_turn_share(dynamics, turn_rate, speed)
    return base, speed, turn_rate, 1.0 if share is None else share


def gazebo_rudder_control_parameters(dynamics: VesselDynamics, max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of the generated hull with one thruster and a rudder.

    Servo 1 is the helm angle (PWM 1000 to 2000 is hard over to port to hard over to starboard),
    servo 3 the thruster. The feedforward is exact on the steady turn of rudder_reference_turn:
    the rudder angle that holds it (rudder_turn_share) as Rover steering, with Rover's speed
    scaling undone (rover_rudder_steering), over its turn rate.

    Assumptions:

    - Rover scales the rudder by MOT_SPD_SCA_BASE / speed above that speed, while this rudder
      needs a little less at speed (its force grows with the square of the speed, the turn's
      slide with the speed). The base is the speed from which hard over holds the max turn
      rate, so above it full steering is about what the max turn rate needs at any speed, and
      the feedforward is exact at the cruise speed; faster it oversteers and slower it
      understeers, by the speed ratio to a power below one, which the PI terms remove.
    - At or below the base Rover does not scale the rudder and rests the integrator, where the
      rudder cannot hold the max turn rate anyway. A vessel that cruises there turns at what
      hard over gives, and the feedforward is exact at that turn rate.
    - The surge is the cruise speed in the turn (Rover's speed controller holds it), and the
      rudder's own drag is left to the speed controller.
    - The helm's travel is in the gains as a lag (see _helm_control_parameters); the rudder gives
      no force at rest, so the vessel does not turn before it moves.
    - Around the turn, the yaw gain is the slope of the steady turns (a slightly slower turn
      needs slightly less rudder), so it has the slide and the stern's swing in it, which damp
      the yaw more than the hull's own yaw damping does. The slide is taken as settled.
    """
    base, speed, turn_rate, share = rudder_reference_turn(dynamics, max_turn_rate, cruise_speed)
    steering = rover_rudder_steering(share, speed, base)
    angle_per_steering = dynamics.steering_max_angle * steering_share_of_rudder(speed, base)
    lever = abs(dynamics.steering_x)

    slower_rate = (1.0 - RUDDER_GAIN_STEP) * turn_rate
    slower_share = rudder_turn_share(dynamics, slower_rate, speed)
    slower_steering = rover_rudder_steering(0.0 if slower_share is None else slower_share, speed, base)
    yaw_gain = (turn_rate - slower_rate) / (steering - slower_steering)

    _, sway_at_rudder = _rudder_turn_flow(dynamics, turn_rate, speed)
    angle = share * dynamics.steering_max_angle
    angle_step = RUDDER_GAIN_STEP * angle
    force_per_angle = (_rudder_turning_force(dynamics, angle, speed, sway_at_rudder) - _rudder_turning_force(dynamics, angle - angle_step, speed, sway_at_rudder)) / angle_step
    turn = HelmTurn(
        turn_rate=turn_rate,
        steering=steering,
        yaw_gain=yaw_gain,
        moment_per_steering=lever * force_per_angle * angle_per_steering,
        full_moment=abs(dynamics.helm_moment(min(angle_per_steering, dynamics.steering_max_angle), speed, 0.0)),
        helm_time=angle / dynamics.steering_rate,
    )
    return _helm_control_parameters(dynamics, turn, cruise_speed, (("MOT_SPD_SCA_BASE", base),))


def vectored_thrust_steering(dynamics: VesselDynamics, turn_rate: float) -> float:
    """Rover steering that holds a steady turn at turn_rate with the vectored thruster.

    With MOT_VEC_ANGLEMAX set, Rover turns steering s at throttle t into the angle atan(s / t)
    and the throttle t / cos(angle), so the side thrust is s times the full thrust at any
    throttle. At the thruster's lever arm it balances the yaw damping |nR| r + |nRabsR| r^2; the
    hull's slide does not change a thruster's force.
    """
    return damping_force(dynamics.nR, dynamics.nRabsR, turn_rate) / (abs(dynamics.steering_x) * dynamics.total_thrust)


def gazebo_vectored_thrust_control_parameters(dynamics: VesselDynamics, max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of the generated hull with one thruster that turns with the helm.

    Servo 1 is the thruster's angle (PWM 1000 to 2000 is minus to plus the hard over angle,
    which is MOT_VEC_ANGLEMAX), servo 3 its thrust. The feedforward is the steering of
    vectored_thrust_steering over the turn rate, at the vessel's max turn rate.

    Assumptions:

    - Rover limits the steering to throttle * tan(MOT_VEC_ANGLEMAX): the thruster cannot push
      sideways more than its angle allows. At the cruise throttle that may be less than the max
      turn rate needs; the gains are then those of the turn rate the limit holds, and the
      vessel turns faster only while the speed controller adds throttle.
    - The throttle of the turn is the cruise throttle of a straight course (the slide's drag is
      left to the speed controller); the helm's travel to the angle of that turn is in the
      gains as a lag (see _helm_control_parameters).
    - Without thrust the vessel does not turn, as the thruster gives no side force then.
    """
    max_angle = dynamics.steering_max_angle
    cruise = min(cruise_speed, dynamics.design_speed)
    throttle = damping_force(dynamics.xU, dynamics.xUabsU, cruise) / dynamics.total_thrust
    steering_limit = min(1.0, throttle * math.tan(max_angle))
    turn_rate = max_turn_rate
    if vectored_thrust_steering(dynamics, turn_rate) > steering_limit:
        turn_rate = _last_true(lambda rate: vectored_thrust_steering(dynamics, rate) <= steering_limit, 0.0, max_turn_rate)
    if turn_rate <= 0:
        # No thrust at the cruise speed (a vessel at rest): the gains of the smallest turn, which the linear yaw damping sets.
        turn_rate = max_turn_rate * 1e-3
    steering = vectored_thrust_steering(dynamics, turn_rate)
    moment_per_steering = abs(dynamics.steering_x) * dynamics.total_thrust
    yaw_slope = abs(dynamics.nR) + 2.0 * abs(dynamics.nRabsR) * turn_rate
    turn = HelmTurn(
        turn_rate=turn_rate,
        steering=steering,
        yaw_gain=moment_per_steering / yaw_slope,
        moment_per_steering=moment_per_steering,
        full_moment=moment_per_steering * max(steering_limit, steering),
        helm_time=min(math.atan2(steering, throttle), max_angle) / dynamics.steering_rate,
    )
    return _helm_control_parameters(dynamics, turn, cruise_speed, (("MOT_VEC_ANGLEMAX", math.degrees(max_angle)),))


def sitl_rudder_steering(turn_rate: float, speed: float) -> float:
    """Steering that turns SITL's motorboat at turn_rate (rad/s) at speed (m/s), Rover's speed scaling included.

    SITL turns on a circle of SITL_TURNING_CIRCLE_M * sin(35 deg) / sin(s * 35 deg) at the boat's
    speed, and Rover scales steering by MOT_SPD_SCA_BASE / speed above that base speed.
    """
    rudder_max = math.radians(SITL_RUDDER_ANGLE_MAX_DEG)
    sine = turn_rate * SITL_TURNING_CIRCLE_M * math.sin(rudder_max) / (2.0 * speed)
    rudder = math.asin(min(1.0, sine)) / rudder_max
    return rudder * max(1.0, speed / MOTOR_SPEED_SCALE_BASE)


def sitl_skid_steering(turn_rate: float, speed: float) -> float:
    """Steering that turns SITL's skid steered boat at turn_rate (rad/s) at speed (m/s); 1 when full differential thrust does not reach it.

    SITL takes the left motor minus the right one as the boat's rudder, which is twice Rover's
    steering (left = throttle + steering, right = throttle - steering), and turns on the
    motorboat's circle for that rudder. Rover does not scale skid steering with the speed. At
    rest the boat pivots at SITL_SKID_PIVOT_RATE per unit of rudder instead.
    """
    if speed <= 0:
        return min(1.0, turn_rate / (SITL_SKID_RUDDER_PER_STEERING * SITL_SKID_PIVOT_RATE))
    rudder_max = math.radians(SITL_RUDDER_ANGLE_MAX_DEG)
    sine = turn_rate * SITL_TURNING_CIRCLE_M * math.sin(rudder_max) / (2.0 * speed)
    if sine >= math.sin(SITL_SKID_RUDDER_PER_STEERING * rudder_max):
        return 1.0
    return math.asin(sine) / rudder_max / SITL_SKID_RUDDER_PER_STEERING


def _sitl_boat_control_parameters(steering_type: SteeringType, turn_rate_ff: float, cruise: float) -> ControlParameters:
    """Gains of SITL's boat around a feedforward: its turn rate follows the steering at once, its speed settles at 10 sqrt(throttle) m/s."""
    servo1_function, servo3_function, skid_steering = steering_outputs(steering_type)
    # No yaw inertia: the turn rate loop only trims the feedforward, and the heading loop is
    # limited by Rover's 50 Hz scheduler and the rate filter, not by the plant.
    cruise_throttle = SITL_HULL_DRAG_COEFFICIENT * cruise**2 / SITL_THRUST_PER_THROTTLE_N
    surge_slope = 2.0 * SITL_HULL_DRAG_COEFFICIENT * cruise
    speed_p = (SPEED_LOOP_SPEEDUP - 1.0) * surge_slope / SITL_THRUST_PER_THROTTLE_N
    return ControlParameters(
        servo1_function=servo1_function,
        servo3_function=servo3_function,
        skid_steering=skid_steering,
        turn_rate_ff=turn_rate_ff,
        turn_rate_p=0.5 * turn_rate_ff,
        turn_rate_i=0.5 * turn_rate_ff,
        heading_p=2.0,
        turn_accel_max_deg=0.0,
        cruise_throttle_percent=_cruise_throttle(cruise_throttle),
        speed_p=speed_p,
        speed_i=speed_p * surge_slope / SITL_BOAT_MASS_KG,
        top_speed=SITL_TOP_SPEED,
    )


def sitl_motorboat_control_parameters(max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of SITL's motorboat: a rudder whose turn rate follows the steering at once (no yaw inertia),
    and a hull whose speed settles at 10 sqrt(throttle) m/s."""
    cruise = min(cruise_speed, SITL_TOP_SPEED)
    reference_speed = max(cruise, MOTOR_SPEED_SCALE_BASE)
    turn_rate_ff = sitl_rudder_steering(max_turn_rate, reference_speed) / max_turn_rate
    return _sitl_boat_control_parameters(SteeringType.RUDDER, turn_rate_ff, cruise)


def sitl_skid_boat_control_parameters(max_turn_rate: float, cruise_speed: float) -> ControlParameters:
    """Gains of SITL's skid steered boat (frame motorboat-skid): the motorboat's hull and turning circle,
    steered by the difference of its two motors and driven by their mean (50 N per unit of it)."""
    cruise = min(cruise_speed, SITL_TOP_SPEED)
    turn_rate_ff = sitl_skid_steering(max_turn_rate, cruise) / max_turn_rate
    return _sitl_boat_control_parameters(SteeringType.SKID, turn_rate_ff, cruise)


def control_parameters(
    vessel: ConcreteVessel, cruise_speed: float, simulation_layer: SimulationLayerId, wind_speed: float = 0.0, overrides: Optional[Mapping[str, float]] = None
) -> Optional[ControlParameters]:
    """The plant's gains for the vessel's steering type, or None for a vessel that cannot turn or move (no control law to derive).

    ValueError for a simulation layer ArduPilot does not drive, and for a steering type the layer
    does not simulate (vectored thrust on ardupilot_sim, which the resolver refuses beforehand).
    """
    steering_type = vessel.steering_type
    sitl_frame(steering_type, simulation_layer, vessel.id)  # raises for what the layer does not simulate
    if vessel.max_angular_speed <= 0 or vessel.max_speed <= 0:
        return None
    if simulation_layer == SimulationLayerId.GAZEBO:
        if overrides is None:
            from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides

            overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
        dynamics = derive_vessel_dynamics(vessel, wind_speed, overrides)
        if steering_type == SteeringType.RUDDER:
            return gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, cruise_speed)
        if steering_type == SteeringType.VECTORED_THRUST:
            return gazebo_vectored_thrust_control_parameters(dynamics, vessel.max_angular_speed, cruise_speed)
        return gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise_speed)
    if steering_type == SteeringType.RUDDER:
        return sitl_motorboat_control_parameters(vessel.max_angular_speed, cruise_speed)
    return sitl_skid_boat_control_parameters(vessel.max_angular_speed, cruise_speed)


def generate_ardu_params(
    vessel: ConcreteVessel,
    cruise_speed: float,
    wind: np.ndarray,
    wave: WaveConfig,
    simulation_layer: SimulationLayerId = SimulationLayerId.ARDUPILOT_SIM,
    *,
    guided_targets: bool = False,
    overrides: Optional[Mapping[str, float]] = None,
) -> dict:
    """ArduPilot Rover parameters of a vessel on a simulation layer.

    cruise_speed is the trajectory's max speed. guided_targets: the vessel is driven by GUIDED
    heading and speed targets (the lockstep MAVLink adapters), so WP_SPEED, which caps those
    targets, is the vessel's max speed; otherwise it is the cruise speed of an ArduAgent mission.
    overrides are the vessel dynamics overrides of a gazebo hull (the vessel_dynamics files' when None).
    The outputs follow the vessel's steering type; a steering type the layer does not simulate is a ValueError.
    """
    max_turn_rate = vessel.max_angular_speed
    controls = control_parameters(vessel, cruise_speed, simulation_layer, float(np.linalg.norm(wind)), overrides)
    top_speed = controls.top_speed if controls is not None else vessel.max_speed
    speed_limit = min(vessel.max_speed, top_speed)
    cruise = min(cruise_speed, speed_limit)

    # Rover limits the turn rate to TURN_MAX_G * g / speed as well. At least 1 g keeps that limit
    # above ATC_STR_RAT_MAX at every speed the vessel reaches, so only the vessel's turn rate applies.
    turning_radius = vessel.max_speed / max_turn_rate if max_turn_rate > 0 else vessel.length * 5
    turn_max_g = max(vessel.max_speed**2 / (turning_radius * GRAVITY), 1.0)

    # Waypoint capture geometry of ArduAgent missions. ConcreteVessel.waypoint_radius is length * 4.0;
    # clamped so tiny USVs still get a usable radius and very long vessels do not get an absurd one
    # relative to the thinned mission leg length. The overshoot lets the hull re-intercept a leg after
    # a tight corner instead of looping back to the missed point.
    wp_radius = float(np.clip(vessel.waypoint_radius, 3.0, 150.0))
    wp_overshoot = float(np.clip(turning_radius * 0.5, wp_radius, 200.0))

    params = {
        # Frame and mode
        "FRAME_CLASS": 2,  # 2 = boat
        "INITIAL_MODE": 10,  # 10 = Auto
        # Navigation. 0 disables pivot turns, so a skid-steered hull arcs through corners.
        "WP_PIVOT_ANGLE": 0,
        "WP_RADIUS": wp_radius,
        "WP_OVERSHOOT": wp_overshoot,
        "WP_SPEED": speed_limit if guided_targets else cruise,
        "CRUISE_SPEED": cruise,
        "SPEED_MAX": top_speed,
        # Longitudinal limits: the vessel's acceleration both ways, as the kinematic layer applies it.
        "ATC_ACCEL_MAX": vessel.max_acceleration,
        "ATC_DECEL_MAX": vessel.max_acceleration,
        # Lateral limits
        "TURN_MAX_G": turn_max_g,
        "ATC_STR_RAT_MAX": math.degrees(max_turn_rate),
        # Outputs: PWM 1500 is neutral for both thrusters and for the helm.
        "SERVO1_MIN": 1000,
        "SERVO1_MAX": 2000,
        "SERVO1_TRIM": 1500,
        "SERVO3_MIN": 1000,
        "SERVO3_MAX": 2000,
        "SERVO3_TRIM": 1500,
        "SERVO_32_ENABLE": 0,
        "BATT_MONITOR": 4,
        # Failsafes and arming checks: off in simulation
        "ARMING_CHECK": 0,
        "ARMING_REQUIRE": 0,  # no arming required
        "FS_GCS_ENABLE": 0,
        "FS_THR_ENABLE": 0,
        "FS_CRASH_CHECK": 0,
        "FS_EKF_ACTION": 0,
        "BAT_FS": 0,
        "FS_ACTION": 0,
        "FS_TIMEOUT": 60,
    }
    if controls is not None:
        params.update(controls.as_params())
        if controls.turn_accel_max_deg > 0:
            params["ATC_STR_ACC_MAX"] = controls.turn_accel_max_deg
    else:
        servo1_function, servo3_function, skid_steering = steering_outputs(vessel.steering_type)
        params.update({"SERVO1_FUNCTION": servo1_function, "SERVO3_FUNCTION": servo3_function, "SKID_STEER_OUT": 1 if skid_steering else 0})

    environment_params = {
        "SIM_WIND_SPD": np.linalg.norm(wind),  # wind speed in m/s
        "SIM_WIND_DIR": np.degrees(np.arctan2(wind[1], wind[0])),
        "SIM_WIND_TURB": 0,
        "SIM_WIND_DIR_Z": 0,
        "SIM_WAVE_ENABLE": 1 if wave.is_enabled else 0,
        "SIM_WAVE_AMP": wave.amplitude,  # m
        "SIM_WAVE_DIR": np.degrees(np.arctan2(wave.direction[1], wave.direction[0])),
        "SIM_WAVE_LENGTH": wave.length,
        "SIM_WAVE_SPEED": wave.speed,
    }
    return {**params, **environment_params}
