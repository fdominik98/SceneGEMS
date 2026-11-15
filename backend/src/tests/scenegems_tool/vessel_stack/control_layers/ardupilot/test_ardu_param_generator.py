"""generate_ardu_params: ArduPilot Rover parameters from the vessel's limits and steering type, the plant's dynamics and the environment."""

import dataclasses
import math

import numpy as np
import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import VESSEL_SCALES, scaled_vessel
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import (
    HELM_LAG_GAIN_LIMIT,
    RATE_LOOP_SPEEDUP,
    SITL_BOAT_MASS_KG,
    SITL_HULL_DRAG_COEFFICIENT,
    SITL_RUDDER_ANGLE_MAX_DEG,
    SITL_THRUST_PER_THROTTLE_N,
    SITL_TOP_SPEED,
    SITL_TURNING_CIRCLE_M,
    control_parameters,
    gazebo_control_parameters,
    gazebo_rudder_control_parameters,
    gazebo_vectored_thrust_control_parameters,
    generate_ardu_params,
    rudder_authority_speed,
    rudder_reference_turn,
    rudder_turn_share,
    sitl_frame,
    sitl_motorboat_control_parameters,
    sitl_rudder_steering,
    sitl_skid_boat_control_parameters,
    sitl_skid_steering,
    steering_outputs,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import damping_force
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics, steady_turn
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

CALM = EnvironmentConfig.calm()
GAZEBO = SimulationLayerId.GAZEBO
ARDUPILOT_SIM = SimulationLayerId.ARDUPILOT_SIM
SKID, RUDDER, VECTORED_THRUST = "skid", "rudder", "vectored_thrust"
GAINS = ("turn_rate_ff", "turn_rate_p", "turn_rate_i", "heading_p", "turn_accel_max_deg", "speed_p", "speed_i")


def steered(vessel, steering_type: str):
    """The vessel with another steering type (a vessel without one is skid steered)."""
    return dataclasses.replace(vessel, _steering_type=steering_type)


def params_for(vessel, cruise_speed=8.0, wind=None, wave=None, layer=ARDUPILOT_SIM, guided_targets=False):
    return generate_ardu_params(vessel, cruise_speed, CALM.wind_vector if wind is None else wind, CALM.wave if wave is None else wave, layer, guided_targets=guided_targets, overrides={})


def outputs(params) -> tuple:
    return params["SERVO1_FUNCTION"], params["SERVO3_FUNCTION"], params["SKID_STEER_OUT"]


def sitl_turn_rate(steering: float, speed: float) -> float:
    """SITL's motorboat turn rate (rad/s), Sailboat::get_yaw_rate with Rover's steering speed scaling."""
    rudder = steering / max(1.0, speed)
    turn_circle = SITL_TURNING_CIRCLE_M * math.sin(math.radians(SITL_RUDDER_ANGLE_MAX_DEG)) / math.sin(math.radians(rudder * SITL_RUDDER_ANGLE_MAX_DEG))
    return speed / (turn_circle / 2.0)


def sitl_skid_turn_rate(steering: float, speed: float) -> float:
    """SITL's skid steered boat turn rate (rad/s): Sailboat::update takes the left motor minus the right one,
    which AP_MotorsUGV::output_skid_steering makes twice the steering, as the rudder of get_yaw_rate; at rest it pivots."""
    rudder = 2.0 * steering
    if speed == 0:
        return math.radians(rudder * math.pi * 5.0)
    turn_circle = SITL_TURNING_CIRCLE_M * math.sin(math.radians(SITL_RUDDER_ANGLE_MAX_DEG)) / math.sin(math.radians(rudder * SITL_RUDDER_ANGLE_MAX_DEG))
    return speed / (turn_circle / 2.0)


def rover_rudder_share(steering: float, speed: float, speed_scale_base: float) -> float:
    """Share of hard over Rover puts a rudder at: AP_MotorsUGV::output_regular scales steering by MOT_SPD_SCA_BASE / speed above that speed, then limits it."""
    if speed_scale_base > 0 and speed > speed_scale_base:
        steering *= speed_scale_base / speed
    return min(steering, 1.0)


def rover_vectored_thrust(steering: float, throttle: float, angle_max: float) -> tuple:
    """(thruster angle in rad, throttle) Rover gives a vectored thruster: AP_MotorsUGV::output_regular with MOT_VEC_ANGLEMAX."""
    steering = min(steering, abs(throttle * math.tan(angle_max)))
    angle = min(math.atan(steering / throttle), angle_max)
    return angle, throttle / math.cos(angle)


def yaw_moment_of_rudder_turn(dynamics, turn_rate: float, speed: float, rudder_share: float) -> tuple:
    """(surge, yaw moment of the helm) of the generator's own steady turn (vessel_dynamics.steady_turn) to port at turn_rate
    with the rudder at rudder_share of hard over, at the thrust that keeps the surge at speed."""
    angle = -rudder_share * dynamics.steering_max_angle

    def turn(thrust: float) -> tuple:
        surge, _, moment = steady_turn(
            turn_rate,
            lambda surge, sway_at_helm: dynamics.helm_force(angle, surge, sway_at_helm, thrust),
            dynamics.total_mass,
            (dynamics.xU, dynamics.xUabsU),
            (dynamics.yV, dynamics.yVabsV),
            dynamics.steering_x,
            dynamics.design_speed,
        )
        return surge, moment

    low, high = 0.0, 4.0 * dynamics.total_thrust
    for _ in range(50):
        middle = (low + high) / 2.0
        if turn(middle)[0] < speed:
            low = middle
        else:
            high = middle
    return turn((low + high) / 2.0)


class TestSpeeds:
    def test_arduagent_missions_cruise_at_the_trajectory_speed(self):
        params = params_for(make_vessel(0, True, max_speed=9.0), cruise_speed=8.0)
        assert params["WP_SPEED"] == params["CRUISE_SPEED"] == 8.0

    def test_guided_targets_are_capped_at_the_vessels_max_speed_not_the_cruise_speed(self):
        """Rover clamps GUIDED speed targets to WP_SPEED; the cruise speed there made the replay follower trail (WP3)."""
        params = params_for(make_vessel(0, True, max_speed=9.0), cruise_speed=8.0, guided_targets=True)
        assert params["WP_SPEED"] == 9.0
        assert params["CRUISE_SPEED"] == 8.0

    def test_speeds_are_capped_at_what_the_plant_reaches(self):
        fast = make_vessel(0, True, max_speed=20.0)
        params = params_for(fast, cruise_speed=12.0, guided_targets=True)
        assert params["SPEED_MAX"] == pytest.approx(SITL_TOP_SPEED)
        assert params["WP_SPEED"] == params["CRUISE_SPEED"] == pytest.approx(SITL_TOP_SPEED)
        gazebo = params_for(fast, cruise_speed=12.0, layer=GAZEBO, guided_targets=True)
        assert gazebo["SPEED_MAX"] == pytest.approx(1.2 * 20.0), "full thrust settles at the control margin times the max speed"
        assert gazebo["WP_SPEED"] == 20.0

    def test_acceleration_limits_follow_the_vessel_both_ways(self):
        params = params_for(make_vessel(0, True, max_acceleration=0.4))
        assert params["ATC_ACCEL_MAX"] == params["ATC_DECEL_MAX"] == 0.4


class TestTurning:
    def test_turn_rate_is_the_max_angular_speed_in_degrees(self):
        for layer in (ARDUPILOT_SIM, GAZEBO):
            assert params_for(make_vessel(0, True, max_angular_speed=0.05), layer=layer)["ATC_STR_RAT_MAX"] == pytest.approx(math.degrees(0.05))

    def test_rollover_protection_is_bypassed_with_at_least_one_g(self):
        assert params_for(make_vessel(0, True))["TURN_MAX_G"] >= 1.0
        # v^2 / (R g) with R = v / omega: a fast turner exceeds 1 g
        fast = make_vessel(0, True, max_speed=30.0, max_angular_speed=3.0)
        assert params_for(fast)["TURN_MAX_G"] == pytest.approx(30.0 * 3.0 / 9.81)

    def test_a_vessel_that_cannot_turn_gets_no_control_law(self):
        vessel = make_vessel(0, True, max_angular_speed=0.0)
        assert control_parameters(vessel, 8.0, GAZEBO, overrides={}) is None
        for layer in (ARDUPILOT_SIM, GAZEBO):
            params = params_for(vessel, layer=layer)
            assert params["TURN_MAX_G"] >= 1.0
            assert params["ATC_STR_RAT_MAX"] == 0.0
            assert "ATC_STR_RAT_FF" not in params

    def test_the_outputs_of_a_vessel_that_cannot_turn_follow_its_steering_type(self):
        vessel = make_vessel(0, True, max_angular_speed=0.0)
        for layer in (ARDUPILOT_SIM, GAZEBO):
            assert outputs(params_for(steered(vessel, SKID), layer=layer)) == (73, 74, 1)
            assert outputs(params_for(steered(vessel, RUDDER), layer=layer)) == (26, 70, 0)
        assert outputs(params_for(steered(vessel, VECTORED_THRUST), layer=GAZEBO)) == (26, 70, 0)
        with pytest.raises(ValueError, match="vectored thrust steering"):
            params_for(steered(vessel, VECTORED_THRUST), layer=ARDUPILOT_SIM)


class TestOutputs:
    def test_a_vessel_without_a_steering_type_is_skid_steered(self):
        assert make_vessel(0, True).steering_type.value == SKID

    def test_a_skid_vessel_on_gazebo_steers_by_the_two_thrusters(self):
        assert outputs(params_for(steered(make_vessel(0, True), SKID), layer=GAZEBO)) == (73, 74, 1)

    @pytest.mark.parametrize("steering_type", [RUDDER, VECTORED_THRUST])
    def test_a_vessel_with_a_helm_on_gazebo_drives_the_helm_and_one_thruster(self, steering_type):
        """The generated model takes servo 1 as the helm angle and servo 3 as the thrust of its one thruster."""
        assert outputs(params_for(steered(make_vessel(0, True), steering_type), layer=GAZEBO)) == (26, 70, 0)

    def test_a_rudder_vessel_on_ardupilot_sim_drives_a_rudder_and_a_throttle(self):
        assert outputs(params_for(steered(make_vessel(0, True), RUDDER))) == (26, 70, 0)

    def test_a_skid_vessel_on_ardupilot_sim_drives_the_two_motors(self):
        """With the frame motorboat-skid; on the frame motorboat SITL read the left motor as its rudder, so the boat crept at rest (WP3)."""
        assert outputs(params_for(steered(make_vessel(0, True), SKID))) == (73, 74, 1)

    def test_vectored_thrust_on_ardupilot_sim_is_an_error_that_names_the_vessel_and_the_reason(self):
        vessel = steered(make_vessel(7, True), VECTORED_THRUST)
        with pytest.raises(ValueError, match="vessel 7 has vectored thrust steering, which the ardupilot_sim simulation layer does not simulate"):
            params_for(vessel)
        with pytest.raises(ValueError, match="vectored thrust steering"):
            control_parameters(vessel, 8.0, ARDUPILOT_SIM)

    def test_the_vectored_thrust_angle_is_set_for_vectored_thrust_only(self):
        vessel = make_vessel(0, True)
        assert params_for(steered(vessel, VECTORED_THRUST), layer=GAZEBO)["MOT_VEC_ANGLEMAX"] == pytest.approx(30.0)
        for steering_type, layer in ((SKID, GAZEBO), (RUDDER, GAZEBO), (SKID, ARDUPILOT_SIM), (RUDDER, ARDUPILOT_SIM)):
            assert "MOT_VEC_ANGLEMAX" not in params_for(steered(vessel, steering_type), layer=layer), (steering_type, layer)

    def test_the_speed_scale_base_is_set_for_a_gazebo_rudder_only(self):
        vessel = make_vessel(0, True)
        assert params_for(steered(vessel, RUDDER), layer=GAZEBO)["MOT_SPD_SCA_BASE"] > 0
        for steering_type, layer in ((SKID, GAZEBO), (VECTORED_THRUST, GAZEBO), (SKID, ARDUPILOT_SIM), (RUDDER, ARDUPILOT_SIM)):
            assert "MOT_SPD_SCA_BASE" not in params_for(steered(vessel, steering_type), layer=layer), (steering_type, layer)

    def test_steering_outputs_of_each_steering_type(self):
        assert steering_outputs(make_vessel(0, True).steering_type) == (73, 74, True)
        assert steering_outputs(steered(make_vessel(0, True), RUDDER).steering_type) == (26, 70, False)
        assert steering_outputs(steered(make_vessel(0, True), VECTORED_THRUST).steering_type) == (26, 70, False)

    def test_neutral_pwm_is_1500_on_both_outputs(self):
        for steering_type in (SKID, RUDDER):
            params = params_for(steered(make_vessel(0, True), steering_type))
            assert params["SERVO1_TRIM"] == params["SERVO3_TRIM"] == 1500


class TestSitlFrame:
    def test_the_frame_on_ardupilot_sim_follows_the_steering_type(self):
        vessel = make_vessel(0, True)
        assert sitl_frame(steered(vessel, RUDDER).steering_type, ARDUPILOT_SIM) == "motorboat"
        assert sitl_frame(steered(vessel, SKID).steering_type, ARDUPILOT_SIM) == "motorboat-skid"

    def test_the_skid_frame_is_one_sitl_steers_by_its_motors(self):
        """Sailboat::Sailboat: skid steering when the frame name holds "skid"; the model table matches the prefix motorboat."""
        frame = sitl_frame(make_vessel(0, True).steering_type, ARDUPILOT_SIM)
        assert frame.startswith("motorboat") and "skid" in frame

    def test_the_frame_on_gazebo_is_the_same_for_every_steering_type(self):
        vessel = make_vessel(0, True)
        assert {sitl_frame(steered(vessel, steering_type).steering_type, GAZEBO) for steering_type in (SKID, RUDDER, VECTORED_THRUST)} == {"motorboat"}

    def test_vectored_thrust_has_no_frame_on_ardupilot_sim(self):
        with pytest.raises(ValueError, match="vessel 3 has vectored thrust steering"):
            sitl_frame(steered(make_vessel(3, True), VECTORED_THRUST).steering_type, ARDUPILOT_SIM, 3)

    def test_a_layer_ardupilot_does_not_drive_has_no_frame(self):
        with pytest.raises(ValueError, match="kinematic"):
            sitl_frame(make_vessel(0, True).steering_type, SimulationLayerId.KINEMATIC)


class TestGazeboHullGains:
    @pytest.fixture(params=sorted(VESSEL_SCALES))
    def hull(self, request):
        vessel = scaled_vessel(request.param)
        return vessel, derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES[request.param].cruise_speed

    def test_the_turn_rate_feedforward_balances_the_yaw_damping_at_the_max_turn_rate(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        rate = vessel.max_angular_speed
        steering = controls.turn_rate_ff * rate
        moment = 2.0 * steering * dynamics.max_thrust * dynamics.thruster_y
        assert moment == pytest.approx(abs(dynamics.nR) * rate + abs(dynamics.nRabsR) * rate**2)
        assert 0.0 < steering < 1.0, "the max turn rate needs less than full differential thrust"

    def test_the_cruise_throttle_balances_the_surge_damping_at_the_cruise_speed(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        thrust = controls.cruise_throttle_percent / 100.0 * 2.0 * dynamics.max_thrust
        assert thrust == pytest.approx(abs(dynamics.xU) * cruise + abs(dynamics.xUabsU) * cruise**2)
        assert controls.top_speed == pytest.approx(dynamics.design_speed)

    def test_every_gain_is_positive_and_finite(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        for name in ("turn_rate_ff", "turn_rate_p", "turn_rate_i", "heading_p", "turn_accel_max_deg", "speed_p", "speed_i"):
            value = getattr(controls, name)
            assert math.isfinite(value) and value > 0, name

    def test_the_turn_acceleration_limit_is_what_full_differential_thrust_gives(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        full = 2.0 * dynamics.max_thrust * dynamics.thruster_y / (dynamics.hull_izz + abs(dynamics.nDotR))
        assert controls.turn_accel_max_deg == pytest.approx(math.degrees(full))

    def test_gazebo_params_carry_the_hull_gains(self):
        vessel = scaled_vessel("30m")
        params = params_for(vessel, layer=GAZEBO)
        controls = gazebo_control_parameters(derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed, 8.0)
        assert params["ATC_STR_RAT_FF"] == controls.turn_rate_ff
        assert params["ATC_STR_ANG_P"] == controls.heading_p
        assert params["ATC_SPEED_P"] == controls.speed_p
        assert params["ATC_STR_ACC_MAX"] == controls.turn_accel_max_deg
        assert params["CRUISE_THROTTLE"] == controls.cruise_throttle_percent

    def test_a_larger_hull_needs_more_steering_per_turn_rate(self):
        gains = [gazebo_control_parameters(derive_vessel_dynamics(scaled_vessel(scale), 0.0, {}), scaled_vessel(scale).max_angular_speed, 8.0).turn_rate_ff for scale in ("5m", "30m", "100m")]
        assert gains == sorted(gains)


class TestGazeboRudderHullGains:
    @pytest.fixture(params=sorted(VESSEL_SCALES))
    def hull(self, request):
        vessel = steered(scaled_vessel(request.param), RUDDER)
        return vessel, derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES[request.param].cruise_speed

    @pytest.mark.parametrize("scale", ["30m", "100m"])
    def test_the_feedforward_holds_the_max_turn_rate_at_the_cruise_speed_on_the_generators_steady_turn(self, scale):
        vessel = steered(scaled_vessel(scale), RUDDER)
        dynamics, cruise, rate = derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES[scale].cruise_speed, vessel.max_angular_speed
        controls = gazebo_rudder_control_parameters(dynamics, rate, cruise)
        share = rover_rudder_share(controls.turn_rate_ff * rate, cruise, dict(controls.extra)["MOT_SPD_SCA_BASE"])
        assert 0.0 < share < 1.0, "the max turn rate needs less than hard over at the cruise speed"
        surge, moment = yaw_moment_of_rudder_turn(dynamics, rate, cruise, share)
        assert surge == pytest.approx(cruise, rel=1e-6)
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, rate), rel=1e-4), "the helm's moment balances the yaw damping of that turn"

    def test_a_turn_takes_more_rudder_than_a_straight_course_suggests(self):
        """The hull slides outward and the stern swings, which eases the rudder's angle of attack."""
        vessel = steered(scaled_vessel("30m"), RUDDER)
        dynamics, rate = derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed
        share = rudder_turn_share(dynamics, rate, 8.0)
        straight = abs(dynamics.helm_moment(share * dynamics.steering_max_angle, 8.0, 0.0))
        assert straight > 1.5 * damping_force(dynamics.nR, dynamics.nRabsR, rate)

    def test_the_rudder_needs_less_angle_at_speed_and_none_holds_the_turn_when_slow(self, hull):
        vessel, dynamics, _ = hull
        rate = 0.5 * dynamics.max_steady_yaw_rate
        fast, faster = rudder_turn_share(dynamics, rate, 0.75 * vessel.max_speed), rudder_turn_share(dynamics, rate, vessel.max_speed)
        assert 0.0 < faster < fast < 1.0
        assert rudder_turn_share(dynamics, rate, 0.01 * vessel.max_speed) is None

    def test_the_speed_scale_base_is_the_speed_from_which_hard_over_holds_the_max_turn_rate(self, hull):
        vessel, dynamics, cruise = hull
        base = dict(gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, cruise).extra)["MOT_SPD_SCA_BASE"]
        assert base == pytest.approx(rudder_authority_speed(dynamics, vessel.max_angular_speed))
        assert 0.0 < base < dynamics.design_speed
        assert rudder_turn_share(dynamics, vessel.max_angular_speed, 1.001 * base) == pytest.approx(1.0, abs=0.01)
        assert rudder_turn_share(dynamics, vessel.max_angular_speed, 0.999 * base) is None

    def test_a_vessel_that_cruises_below_that_speed_gets_the_feedforward_of_the_turn_hard_over_holds(self):
        """The 5 m vessel's rudder holds its 0.5 rad/s only above its 3 m/s cruise speed."""
        vessel = steered(scaled_vessel("5m"), RUDDER)
        dynamics, cruise = derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES["5m"].cruise_speed
        base, speed, turn_rate, share = rudder_reference_turn(dynamics, vessel.max_angular_speed, cruise)
        assert cruise < base and speed == cruise
        assert 0.0 < turn_rate < vessel.max_angular_speed
        assert share == pytest.approx(1.0, abs=1e-3)
        controls = gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        assert rover_rudder_share(controls.turn_rate_ff * turn_rate, cruise, base) == pytest.approx(share)
        _, moment = yaw_moment_of_rudder_turn(dynamics, turn_rate, cruise, share)
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, turn_rate), rel=1e-2)

    def test_a_slow_cruise_keeps_the_gains_of_half_the_speed_scale_base(self, hull):
        vessel, dynamics, _ = hull
        base, speed, _, _ = rudder_reference_turn(dynamics, vessel.max_angular_speed, 0.0)
        assert speed == pytest.approx(0.5 * base)
        at_rest, slow = gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, 0.0), gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, 0.1 * base)
        assert at_rest.turn_rate_ff == slow.turn_rate_ff and math.isfinite(at_rest.turn_rate_ff)

    def test_every_gain_is_positive_and_finite(self, hull):
        vessel, dynamics, cruise = hull
        for speed in (0.0, cruise, vessel.max_speed):
            controls = gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, speed)
            for name in GAINS:
                value = getattr(controls, name)
                assert math.isfinite(value) and value > 0, (name, speed)

    def test_the_cruise_throttle_balances_the_surge_damping_with_the_one_thruster(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        assert dynamics.thruster_count == 1
        assert controls.cruise_throttle_percent / 100.0 * dynamics.max_thrust == pytest.approx(abs(dynamics.xU) * cruise + abs(dynamics.xUabsU) * cruise**2)
        assert controls.top_speed == pytest.approx(dynamics.design_speed)

    def test_the_loop_waits_for_the_helm(self, hull):
        """The turn rate is not asked to change faster than the helm reaches the angle of the turn, and the loop gain stays below the helm's limit."""
        vessel, dynamics, cruise = hull
        controls = gazebo_rudder_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        _, _, turn_rate, share = rudder_reference_turn(dynamics, vessel.max_angular_speed, cruise)
        helm_time = share * dynamics.steering_max_angle / dynamics.steering_rate
        assert math.radians(controls.turn_accel_max_deg) <= turn_rate / helm_time * (1 + 1e-9)
        yaw_time_constant = controls.turn_rate_p / controls.turn_rate_i
        loop_gain_limit = min(RATE_LOOP_SPEEDUP - 1.0, yaw_time_constant / (HELM_LAG_GAIN_LIMIT * helm_time))
        heading_loop_time = 1.0 / controls.heading_p
        assert heading_loop_time == pytest.approx(2.0 * (yaw_time_constant / (1.0 + loop_gain_limit) + helm_time))

    def test_gazebo_params_carry_the_rudder_hull_gains(self):
        vessel = steered(scaled_vessel("30m"), RUDDER)
        params = params_for(vessel, layer=GAZEBO)
        controls = gazebo_rudder_control_parameters(derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed, 8.0)
        assert params["ATC_STR_RAT_FF"] == controls.turn_rate_ff
        assert params["ATC_STR_RAT_P"] == controls.turn_rate_p
        assert params["ATC_STR_ANG_P"] == controls.heading_p
        assert params["ATC_STR_ACC_MAX"] == controls.turn_accel_max_deg
        assert params["MOT_SPD_SCA_BASE"] == dict(controls.extra)["MOT_SPD_SCA_BASE"]
        assert params["SPEED_MAX"] == pytest.approx(1.2 * vessel.max_speed)


class TestGazeboVectoredThrustHullGains:
    @pytest.fixture(params=sorted(VESSEL_SCALES))
    def hull(self, request):
        vessel = steered(scaled_vessel(request.param), VECTORED_THRUST)
        return vessel, derive_vessel_dynamics(vessel, 0.0, {}), VESSEL_SCALES[request.param].cruise_speed

    def test_the_feedforward_balances_the_yaw_damping_at_the_max_turn_rate_through_rovers_vectoring(self, hull):
        vessel, dynamics, cruise = hull
        rate = vessel.max_angular_speed
        controls = gazebo_vectored_thrust_control_parameters(dynamics, rate, cruise)
        throttle = controls.cruise_throttle_percent / 100.0
        angle, throttle_out = rover_vectored_thrust(controls.turn_rate_ff * rate, throttle, math.radians(dict(controls.extra)["MOT_VEC_ANGLEMAX"]))
        assert 0.0 < angle < dynamics.steering_max_angle, "the max turn rate needs less than hard over at the cruise throttle"
        moment = abs(dynamics.helm_moment(angle, cruise, throttle_out * dynamics.total_thrust))
        assert moment == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, rate))
        forward, _ = dynamics.helm_force(angle, cruise, 0.0, throttle_out * dynamics.total_thrust)
        assert forward == pytest.approx(throttle * dynamics.total_thrust), "Rover's throttle scaling keeps the forward thrust"

    def test_the_vectoring_angle_is_the_models_hard_over_angle(self, hull):
        vessel, dynamics, cruise = hull
        controls = gazebo_vectored_thrust_control_parameters(dynamics, vessel.max_angular_speed, cruise)
        assert dict(controls.extra) == {"MOT_VEC_ANGLEMAX": pytest.approx(math.degrees(dynamics.steering_max_angle))}

    def test_a_cruise_throttle_too_low_for_the_max_turn_rate_gets_the_gains_of_the_turn_hard_over_holds(self):
        vessel = steered(scaled_vessel("30m"), VECTORED_THRUST)
        dynamics, rate, cruise = derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed, 4.0
        controls = gazebo_vectored_thrust_control_parameters(dynamics, rate, cruise)
        throttle = damping_force(dynamics.xU, dynamics.xUabsU, cruise) / dynamics.total_thrust
        limit = throttle * math.tan(dynamics.steering_max_angle)
        assert controls.turn_rate_ff * rate > limit, "the max turn rate asks for more side thrust than the angle allows"
        held = limit / controls.turn_rate_ff
        angle, throttle_out = rover_vectored_thrust(limit, throttle, dynamics.steering_max_angle)
        assert angle == pytest.approx(dynamics.steering_max_angle)
        assert abs(dynamics.helm_moment(angle, cruise, throttle_out * dynamics.total_thrust)) == pytest.approx(damping_force(dynamics.nR, dynamics.nRabsR, held), rel=1e-6)

    def test_every_gain_is_positive_and_finite(self, hull):
        vessel, dynamics, cruise = hull
        for speed in (0.0, cruise, vessel.max_speed):
            controls = gazebo_vectored_thrust_control_parameters(dynamics, vessel.max_angular_speed, speed)
            for name in GAINS:
                value = getattr(controls, name)
                assert math.isfinite(value) and value >= 0, (name, speed)
                assert value > 0 or (name == "turn_accel_max_deg" and speed == 0.0), (name, speed)

    def test_gazebo_params_carry_the_vectored_thrust_hull_gains(self):
        vessel = steered(scaled_vessel("30m"), VECTORED_THRUST)
        params = params_for(vessel, layer=GAZEBO)
        controls = gazebo_vectored_thrust_control_parameters(derive_vessel_dynamics(vessel, 0.0, {}), vessel.max_angular_speed, 8.0)
        assert params["ATC_STR_RAT_FF"] == controls.turn_rate_ff
        assert params["ATC_STR_RAT_I"] == controls.turn_rate_i
        assert params["ATC_STR_ANG_P"] == controls.heading_p
        assert params["CRUISE_THROTTLE"] == controls.cruise_throttle_percent


class TestSitlSkidBoatGains:
    @pytest.mark.parametrize("rate, speed", [(0.5, 3.0), (0.05, 8.0), (0.008, 8.0), (0.3, 0.8), (0.2, 0.0)])
    def test_skid_steering_inverts_the_sitl_turn_rate(self, rate, speed):
        assert sitl_skid_turn_rate(sitl_skid_steering(rate, speed), speed) == pytest.approx(rate)

    def test_skid_steering_is_half_the_rudder_and_not_scaled_with_the_speed(self):
        """The two motors differ by twice the steering, and Rover scales only rudder steering down with the speed."""
        assert sitl_skid_steering(0.05, 8.0) == pytest.approx(sitl_rudder_steering(0.05, 8.0) / 8.0 / 2.0)

    def test_full_differential_thrust_when_the_turn_rate_is_out_of_reach(self):
        assert sitl_skid_steering(5.0, 0.5) == 1.0
        assert sitl_skid_steering(5.0, 0.0) == 1.0

    def test_the_feedforward_turns_at_the_max_turn_rate_at_cruise_speed(self):
        controls = sitl_skid_boat_control_parameters(0.5, 3.0)
        assert sitl_skid_turn_rate(controls.turn_rate_ff * 0.5, 3.0) == pytest.approx(0.5)
        assert (controls.servo1_function, controls.servo3_function, controls.skid_steering) == (73, 74, True)

    def test_the_hull_and_its_speed_loop_are_the_motorboats(self):
        """The mean of the two motors drives the boat with the motorboat's 50 N per unit throttle."""
        skid, rudder = sitl_skid_boat_control_parameters(0.05, 8.0), sitl_motorboat_control_parameters(0.05, 8.0)
        for name in ("cruise_throttle_percent", "speed_p", "speed_i", "top_speed", "heading_p", "turn_accel_max_deg"):
            assert getattr(skid, name) == getattr(rudder, name), name

    def test_every_gain_is_positive_and_finite(self):
        for cruise in (0.0, 3.0, 8.0, 20.0):
            controls = sitl_skid_boat_control_parameters(0.05, cruise)
            for name in ("turn_rate_ff", "turn_rate_p", "turn_rate_i", "heading_p"):
                value = getattr(controls, name)
                assert math.isfinite(value) and value > 0, (name, cruise)

    def test_ardupilot_sim_params_carry_the_gains_of_the_vessels_steering_type(self):
        vessel = make_vessel(0, True, max_angular_speed=0.05)
        assert params_for(steered(vessel, SKID))["ATC_STR_RAT_FF"] == sitl_skid_boat_control_parameters(0.05, 8.0).turn_rate_ff
        assert params_for(steered(vessel, RUDDER))["ATC_STR_RAT_FF"] == sitl_motorboat_control_parameters(0.05, 8.0).turn_rate_ff


class TestSitlMotorboatGains:
    @pytest.mark.parametrize("rate, speed", [(0.5, 3.0), (0.05, 8.0), (0.008, 8.0), (0.3, 0.8)])
    def test_rudder_steering_inverts_the_sitl_turn_rate(self, rate, speed):
        assert sitl_turn_rate(sitl_rudder_steering(rate, speed), speed) == pytest.approx(rate)

    def test_the_feedforward_turns_at_the_max_turn_rate_at_cruise_speed(self):
        controls = sitl_motorboat_control_parameters(0.5, 3.0)
        assert sitl_turn_rate(controls.turn_rate_ff * 0.5, 3.0) == pytest.approx(0.5)

    def test_the_cruise_throttle_balances_the_hull_drag(self):
        controls = sitl_motorboat_control_parameters(0.05, 8.0)
        assert controls.cruise_throttle_percent / 100.0 * SITL_THRUST_PER_THROTTLE_N == pytest.approx(SITL_HULL_DRAG_COEFFICIENT * 8.0**2)

    def test_the_speed_integral_follows_the_surge_time_constant(self):
        controls = sitl_motorboat_control_parameters(0.05, 8.0)
        surge_time_constant = SITL_BOAT_MASS_KG / (2 * SITL_HULL_DRAG_COEFFICIENT * 8.0)
        assert controls.speed_i == pytest.approx(controls.speed_p / surge_time_constant)

    def test_a_slow_cruise_keeps_the_throttle_inside_rovers_nudge_range(self):
        assert sitl_motorboat_control_parameters(0.5, 0.5).cruise_throttle_percent == 5.0


class TestWaypointGeometry:
    def test_waypoint_radius_is_clamped(self):
        assert params_for(make_vessel(0, True, length=0.5))["WP_RADIUS"] == 3.0
        assert params_for(make_vessel(0, True, length=1000.0))["WP_RADIUS"] == 150.0
        assert params_for(make_vessel(0, True, length=30.0))["WP_RADIUS"] == 120.0

    def test_overshoot_is_between_the_radius_and_200_meters(self):
        params = params_for(make_vessel(0, True, length=30.0, max_speed=20.0, max_angular_speed=0.05))
        assert params["WP_OVERSHOOT"] == 200.0
        small = params_for(make_vessel(0, True, length=30.0, max_speed=1.0, max_angular_speed=1.0))
        assert small["WP_OVERSHOOT"] == small["WP_RADIUS"]


def test_failsafes_and_arming_checks_are_disabled_for_simulation():
    params = params_for(make_vessel(0, True))
    for name in ("ARMING_CHECK", "ARMING_REQUIRE", "FS_GCS_ENABLE", "FS_THR_ENABLE", "FS_CRASH_CHECK", "FS_EKF_ACTION", "BAT_FS", "FS_ACTION"):
        assert params[name] == 0, name


def test_ardupilot_drives_no_kinematic_layer():
    with pytest.raises(ValueError, match="kinematic"):
        params_for(make_vessel(0, True), layer=SimulationLayerId.KINEMATIC)


class TestEnvironment:
    def test_calm_environment_parameters(self):
        params = params_for(make_vessel(0, True))
        assert params["SIM_WIND_SPD"] == 0
        assert params["SIM_WAVE_ENABLE"] == 0

    def test_wind_speed_is_the_vector_length(self):
        params = params_for(make_vessel(0, True), wind=np.array([3.0, 4.0, 0.0]))
        assert params["SIM_WIND_SPD"] == pytest.approx(5.0)

    def test_waves_enable_the_wave_parameters(self):
        wave = WaveConfig(amplitude=0.5, period=5.0, steepness=0.1, direction=np.array([0.0, 2.0]))
        params = params_for(make_vessel(0, True), wave=wave)
        assert params["SIM_WAVE_ENABLE"] == 1
        assert params["SIM_WAVE_AMP"] == 0.5
        assert params["SIM_WAVE_SPEED"] == 2.0
        assert params["SIM_WAVE_LENGTH"] == pytest.approx(10.0)
        assert params["SIM_WAVE_DIR"] == pytest.approx(90.0)
