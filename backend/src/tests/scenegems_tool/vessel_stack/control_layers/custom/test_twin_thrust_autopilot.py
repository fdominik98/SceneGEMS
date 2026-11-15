"""TwinThrustAutopilot: gains from the hull model, closed-loop heading and speed on it for each steering type, actuator limits and anti-windup."""

import dataclasses
import json
import math

import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import VESSEL_SCALES, scaled_vessel
from scenegems_tool.vessel_stack.control_layers.custom.actuator_allocation import HELM_CROSSING_SHARE
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import (
    DISCRETE_LIMIT,
    HEADING_SEPARATION,
    HELM_SEPARATION,
    RUDDER_SPEED_FLOOR_SHARE,
    AutopilotGains,
    HullObservation,
    TwinThrustAutopilot,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics

CONTROL_DT = 0.1
AT_REST = HullState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
HELM_TYPES = ("rudder", "vectored_thrust")
HELM_HULLS = [(scale, steering) for scale in sorted(VESSEL_SCALES) for steering in HELM_TYPES]


def setup(scale, steering="skid"):
    vessel = dataclasses.replace(scaled_vessel(scale), _steering_type=steering)
    dynamics = derive_vessel_dynamics(vessel, 0.0, {})
    gains = AutopilotGains.from_dynamics(dynamics, vessel, CONTROL_DT)
    return vessel, dynamics, TwinThrustAutopilot(gains), HullSurgeYawModel(dynamics)


def fly(autopilot, model, state, heading, speed, seconds, record=None, states=None):
    for _ in range(int(round(seconds / CONTROL_DT))):
        command = autopilot.command(heading, speed, HullObservation(state.heading, state.surge, state.yaw_rate, state.sway), CONTROL_DT)
        if record is not None:
            record.append(command)
        for _ in range(20):
            state = model.step(state, command.thrusts, command.helm_angle, CONTROL_DT / 20)
        if states is not None:
            states.append(state)
    return state


def cruising(scale, steering):
    """A hull under way at its scale's cruise speed, heading east, with its autopilot started at that speed."""
    vessel, dynamics, autopilot, model = setup(scale, steering)
    cruise = VESSEL_SCALES[scale].cruise_speed
    autopilot.reset(cruise)
    return vessel, dynamics, autopilot, model, HullState(0.0, 0.0, 0.0, cruise, 0.0, 0.0), cruise


class TestGains:
    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_gains_are_positive(self, scale):
        gains = setup(scale)[2].gains
        for name in ("speed_p", "speed_i", "rate_p", "rate_i", "heading_p", "heading_deceleration"):
            assert getattr(gains, name) > 0, name

    def test_the_loop_frequency_respects_the_control_step(self):
        vessel = scaled_vessel("30m")
        dynamics = derive_vessel_dynamics(vessel, 0.0, {})
        coarse = AutopilotGains.from_dynamics(dynamics, vessel, 1.0)
        fine = AutopilotGains.from_dynamics(dynamics, vessel, 0.01)
        assert coarse.heading_p < fine.heading_p
        assert coarse.rate_i / coarse.yaw_inertia == pytest.approx(DISCRETE_LIMIT**2, rel=1e-9)

    def test_the_turn_rate_demand_is_continuous_and_limited(self):
        autopilot = setup("5m")[2]
        demands = [autopilot.turn_rate_demand(math.radians(error)) for error in range(-180, 181)]
        assert max(abs(demand) for demand in demands) <= autopilot.gains.max_turn_rate
        assert all(abs(a - b) < 0.05 for a, b in zip(demands, demands[1:]))
        assert autopilot.turn_rate_demand(0.0) == 0.0
        assert autopilot.turn_rate_demand(0.3) == -autopilot.turn_rate_demand(-0.3)

    def test_a_skid_steered_hull_has_no_steering_gear_in_its_gains(self):
        gains = setup("30m")[2].gains
        assert gains.steering_type == "skid" and gains.thruster_arm > 0
        assert (gains.steering_x, gains.steering_max_angle, gains.steering_rate, gains.helm_yaw_moment, gains.rudder_force_gain, gains.rudder_speed_floor) == (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert gains.max_yaw_moment == 2.0 * gains.max_thrust * gains.thruster_arm

    @pytest.mark.parametrize("scale,steering", HELM_HULLS)
    def test_a_hull_with_a_helm_carries_its_steering_gear(self, scale, steering):
        vessel, dynamics, autopilot, _ = setup(scale, steering)
        gains = autopilot.gains
        assert gains.steering_type == steering and gains.thruster_arm == 0.0
        assert (gains.steering_x, gains.steering_max_angle, gains.steering_rate, gains.steering_speed) == (
            dynamics.steering_x,
            dynamics.steering_max_angle,
            dynamics.steering_rate,
            dynamics.steering_speed,
        )
        assert gains.steering_x < 0.0, "the helm acts aft of midship"
        assert gains.max_yaw_moment == gains.helm_yaw_moment == dynamics.max_yaw_moment > 0.0
        for name in ("speed_p", "speed_i", "rate_i", "heading_p", "heading_deceleration"):
            assert getattr(gains, name) > 0, name
        assert gains.rate_p >= 0.0, "none where the hull's own yaw damping is faster than the helm lets the loop be"
        if steering == "rudder":
            assert gains.rudder_force_gain == pytest.approx(0.5 * 1025.0 * dynamics.rudder_area * dynamics.rudder_lift_slope)
            assert gains.rudder_speed_floor == RUDDER_SPEED_FLOOR_SHARE * vessel.max_speed
        else:
            assert (gains.rudder_force_gain, gains.rudder_speed_floor) == (0.0, 0.0)

    @pytest.mark.parametrize("scale,steering", HELM_HULLS)
    def test_the_turn_rate_loop_is_slower_than_the_helm(self, scale, steering):
        _, dynamics, autopilot, _ = setup(scale, steering)
        rate_frequency = autopilot.gains.heading_p * HEADING_SEPARATION
        to_hard_over_s = dynamics.steering_max_angle / dynamics.steering_rate
        assert rate_frequency <= 1.0 / (HELM_SEPARATION * to_hard_over_s) * (1 + 1e-12)
        assert rate_frequency <= setup(scale)[2].gains.heading_p * HEADING_SEPARATION, "and no faster than on the skid steered hull"

    @pytest.mark.parametrize("scale,steering", HELM_HULLS)
    def test_the_turn_rate_loop_has_its_slower_pole_at_the_loops_frequency(self, scale, steering):
        """m s^2 + (c + P) s + I: a double pole where the loop is faster than half the hull's own rate, else no P and the slower pole there."""
        gains = setup(scale, steering)[2].gains
        frequency = gains.heading_p * HEADING_SEPARATION
        slope = gains.yaw_linear + 2.0 * gains.yaw_quadratic * gains.max_turn_rate
        damping_rate, stiffness = (slope + gains.rate_p) / gains.yaw_inertia, gains.rate_i / gains.yaw_inertia
        discriminant = damping_rate**2 - 4.0 * stiffness
        assert discriminant >= -1e-9 * damping_rate**2, "no oscillating pole pair"
        assert (damping_rate - math.sqrt(max(discriminant, 0.0))) / 2.0 == pytest.approx(frequency, rel=1e-4)
        if gains.rate_p > 0.0:
            assert discriminant == pytest.approx(0.0, abs=1e-9 * damping_rate**2)

    @pytest.mark.parametrize("steering", ["skid", *HELM_TYPES])
    def test_the_gains_travel_as_plain_json(self, steering):
        """The runner sends them to the controller container as a dict."""
        gains = setup("30m", steering)[2].gains
        assert AutopilotGains(**json.loads(json.dumps(dataclasses.asdict(gains)))) == gains

    def test_gains_without_steering_fields_are_a_skid_steered_hulls(self):
        gains = setup("30m")[2].gains
        fields = {field.name: getattr(gains, field.name) for field in dataclasses.fields(gains)[:16]}
        assert AutopilotGains(**fields) == gains

    def test_an_unknown_steering_type_has_no_allocation(self):
        autopilot = setup("5m")[2]
        autopilot.gains = dataclasses.replace(autopilot.gains, steering_type="sail")
        with pytest.raises(ValueError, match="no actuator allocation for steering type 'sail'"):
            autopilot.command(0.0, 1.0, HullObservation(0.0, 0.0, 0.0), CONTROL_DT)


class TestClosedLoop:
    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_it_reaches_the_commanded_speed_and_holds_the_heading(self, scale):
        vessel, _, autopilot, model = setup(scale)
        cruise = VESSEL_SCALES[scale].cruise_speed
        state = fly(autopilot, model, AT_REST, 0.0, cruise, 2 * cruise / vessel.max_acceleration + 120.0)
        assert state.surge == pytest.approx(cruise, rel=1e-3)
        assert abs(state.heading) < 1e-6
        assert abs(state.y) < 1e-6

    @pytest.mark.parametrize("scale", sorted(VESSEL_SCALES))
    def test_a_quarter_turn_completes_without_overshoot(self, scale):
        vessel, _, autopilot, model = setup(scale)
        cruise = VESSEL_SCALES[scale].cruise_speed
        autopilot.reset(cruise)
        state = HullState(0.0, 0.0, 0.0, cruise, 0.0, 0.0)
        quarter_turn_s = (math.pi / 2) / vessel.max_angular_speed
        headings = []
        for _ in range(int(round((4 * quarter_turn_s + 60.0) / CONTROL_DT))):
            state = fly(autopilot, model, state, math.pi / 2, cruise, CONTROL_DT)
            headings.append(state.heading)
        assert max(headings) < math.pi / 2 + math.radians(0.5), "no overshoot beyond half a degree"
        assert headings[-1] == pytest.approx(math.pi / 2, abs=math.radians(0.05))
        assert abs(state.yaw_rate) < 1e-3

    def test_the_speed_reference_ramps_at_the_vessels_max_acceleration(self):
        vessel, _, autopilot, model = setup("30m")
        fly(autopilot, model, AT_REST, 0.0, 8.0, 5.0)
        assert autopilot._speed_reference == pytest.approx(5.0 * vessel.max_acceleration)


@pytest.mark.parametrize("scale,steering", HELM_HULLS)
class TestClosedLoopWithAHelm:
    """A small, a middle and a large vessel, each with a rudder and with vectored thrust."""

    def test_it_reaches_the_commanded_speed_and_holds_the_heading(self, scale, steering):
        vessel, _, autopilot, model = setup(scale, steering)
        cruise = VESSEL_SCALES[scale].cruise_speed
        commands = []
        state = fly(autopilot, model, AT_REST, 0.0, cruise, 2 * cruise / vessel.max_acceleration + 120.0, commands)
        assert state.surge == pytest.approx(cruise, rel=1e-3)
        assert abs(state.heading) < 1e-6 and abs(state.y) < 1e-6
        assert all(command.helm_angle == 0.0 for command in commands), "nothing to steer against"
        assert len(commands[0].thrusts) == 1

    def test_a_quarter_turn_reaches_the_heading_and_stays_there(self, scale, steering):
        vessel, _, autopilot, model, state, cruise = cruising(scale, steering)
        quarter_turn_s = (math.pi / 2) / vessel.max_angular_speed
        seconds = 6 * quarter_turn_s + 120.0
        states, commands = [], []
        state = fly(autopilot, model, state, math.pi / 2, cruise, seconds, commands, states)
        headings = [state.heading for state in states]
        assert max(headings) < math.pi / 2 + math.radians(1.0), "no overshoot beyond a degree"
        assert state.heading == pytest.approx(math.pi / 2, abs=math.radians(0.1))
        assert abs(state.yaw_rate) < 1e-3 * vessel.max_angular_speed + 1e-5
        assert state.surge == pytest.approx(cruise, rel=1e-2)
        # No sustained oscillation: over the last third of the run the heading and the helm are at rest.
        last = len(states) * 2 // 3
        assert max(headings[last:]) - min(headings[last:]) < math.radians(0.1)
        helm = [command.helm_angle for command in commands[last:]]
        assert max(helm) - min(helm) < math.radians(1.0)
        assert max(abs(state.yaw_rate) for state in states) < 1.1 * vessel.max_angular_speed, "the turn stays within the vessel's turn rate"

    def test_a_turn_to_starboard_mirrors_a_turn_to_port(self, scale, steering):
        vessel, _, autopilot, model, state, cruise = cruising(scale, steering)
        seconds = 2 * (math.pi / 6) / vessel.max_angular_speed + 20.0
        to_port, to_starboard = [], []
        port = fly(autopilot, model, state, math.pi / 6, cruise, seconds, to_port)
        autopilot.reset(cruise)
        starboard = fly(autopilot, model, state, -math.pi / 6, cruise, seconds, to_starboard)
        assert port.heading > 0.2 and starboard.heading == pytest.approx(-port.heading, abs=1e-9)
        assert to_port[0].helm_angle < 0.0 < to_starboard[0].helm_angle, "a negative helm angle turns the vessel to port"
        assert [command.thrusts for command in to_starboard] == pytest.approx([command.thrusts for command in to_port])

    def test_the_commands_stay_within_the_thruster_and_the_helm(self, scale, steering):
        vessel, dynamics, autopilot, model = setup(scale, steering)
        commands = []
        fly(autopilot, model, AT_REST, 3.0, vessel.max_speed, 60.0, commands)
        fly(autopilot, model, AT_REST, -1.0, 0.0, 30.0, commands)
        for command in commands:
            assert abs(command.thrusts[0]) <= dynamics.max_thrust + 1e-9
            assert abs(command.helm_angle) <= dynamics.steering_max_angle, "never beyond hard over"

    def test_a_turn_at_low_speed_does_not_oscillate(self, scale, steering):
        """A rudder has a fraction of its force here, and vectored thrust must push to turn: both still settle on the heading."""
        vessel, _, autopilot, model = setup(scale, steering)
        slow = 0.15 * vessel.max_speed
        autopilot.reset(slow)
        seconds = 6 * (math.pi / 2) / vessel.max_angular_speed + 300.0
        states = []
        state = fly(autopilot, model, HullState(0.0, 0.0, 0.0, slow, 0.0, 0.0), math.pi / 2, slow, seconds, states=states)
        headings = [state.heading for state in states]
        assert max(headings) < math.pi / 2 + math.radians(3.0)
        assert state.heading == pytest.approx(math.pi / 2, abs=math.radians(0.1))
        last = len(states) * 2 // 3
        assert max(headings[last:]) - min(headings[last:]) < math.radians(0.2)
        assert state.surge == pytest.approx(slow, rel=2e-2)

    def test_slowing_down_in_a_turn_still_reaches_the_heading(self, scale, steering):
        vessel, _, autopilot, model, state, cruise = cruising(scale, steering)
        seconds = 2 * cruise / vessel.max_acceleration + 6 * (math.pi / 2) / vessel.max_angular_speed + 300.0
        states = []
        state = fly(autopilot, model, state, math.pi / 2, 0.2 * cruise, seconds, states=states)
        assert max(state.heading for state in states) < math.pi / 2 + math.radians(3.0)
        assert state.heading == pytest.approx(math.pi / 2, abs=math.radians(0.1))
        assert state.surge == pytest.approx(0.2 * cruise, rel=2e-2)

    def test_braking_on_a_straight_course_follows_the_speed_reference(self, scale, steering):
        """Both reverse the thrust to brake, as the skid steered hull does, and keep the heading."""
        vessel, _, autopilot, model, state, cruise = cruising(scale, steering)
        ramp_s = 0.8 * cruise / vessel.max_acceleration
        commands = []
        state = fly(autopilot, model, state, 0.0, 0.2 * cruise, ramp_s + 60.0, commands)
        assert state.surge == pytest.approx(0.2 * cruise, rel=2e-2)
        assert min(command.thrusts[0] for command in commands) < 0.0
        assert abs(state.heading) < 1e-6 and all(command.helm_angle == 0.0 for command in commands)


class TestRudder:
    def test_the_yaw_authority_follows_the_speed_squared_up_to_the_steering_speed(self):
        _, dynamics, autopilot, _ = setup("30m", "rudder")
        gains = autopilot.gains
        assert autopilot.yaw_authority(dynamics.steering_speed) == 1.0
        assert autopilot.yaw_authority(2.0 * dynamics.steering_speed) == 1.0
        assert autopilot.yaw_authority(0.5 * dynamics.steering_speed) == pytest.approx(0.25)
        assert autopilot.yaw_authority(-0.5 * dynamics.steering_speed) == pytest.approx(0.25)
        assert autopilot.yaw_authority(0.0) == pytest.approx((gains.rudder_speed_floor / gains.steering_speed) ** 2), "the floor speed's at rest"

    @pytest.mark.parametrize("steering", ["skid", "vectored_thrust"])
    def test_the_other_steering_types_have_their_moment_at_any_speed(self, steering):
        autopilot = setup("30m", steering)[2]
        assert autopilot.yaw_authority(0.0) == 1.0 and autopilot.yaw_authority(3.0) == 1.0

    def test_a_slow_hull_plans_a_gentler_approach(self):
        autopilot = setup("30m", "rudder")[2]
        assert 0.0 < autopilot.turn_rate_demand(1.0, 0.01) < autopilot.turn_rate_demand(1.0, 1.0)
        assert autopilot.turn_rate_demand(1e-3, 0.01) == autopilot.turn_rate_demand(1e-3, 1.0), "near the heading the demand is the linear one either way"

    def test_at_rest_the_helm_goes_hard_over_and_the_yaw_integrator_holds(self):
        """No flow, no rudder force: the helm cannot turn the hull, and once it is hard over waiting does not wind the integrator up."""
        _, dynamics, autopilot, model = setup("30m", "rudder")
        commands = []
        state = fly(autopilot, model, AT_REST, math.pi / 2, 0.0, 300.0, commands)
        assert state.heading == 0.0 and state.surge == 0.0
        assert commands[-1].yaw_saturated and commands[-1].helm_angle == pytest.approx(-dynamics.steering_max_angle)
        assert state.helm_angle == pytest.approx(-dynamics.steering_max_angle)
        held = autopilot._rate_integral
        fly(autopilot, model, state, math.pi / 2, 0.0, 300.0)
        assert autopilot._rate_integral == held

    def test_the_helm_angle_allows_for_the_flow_at_the_stern(self):
        """In a turn to port the stern swings to starboard, and the same moment takes more helm than on a straight course."""
        _, dynamics, autopilot, _ = setup("30m", "rudder")
        straight = autopilot.allocate(0.0, 1e5, HullObservation(0.0, 8.0, 0.0, 0.0), CONTROL_DT)
        turning = autopilot.allocate(0.0, 1e5, HullObservation(0.0, 8.0, 0.03, -0.3), CONTROL_DT)
        assert turning.helm_angle < straight.helm_angle < 0.0
        assert turning.helm_angle - straight.helm_angle == pytest.approx(math.atan((-0.3 + dynamics.steering_x * 0.03) / 8.0), rel=0.02)


class TestVectoredThrust:
    def test_the_autopilot_follows_where_the_helm_is(self):
        """It holds the thrust back while the helm crosses over, so it must know where the model's helm is."""
        _, _, autopilot, model = setup("30m", "vectored_thrust")
        state = AT_REST
        for heading in (1.0, -1.0, 0.3):
            for _ in range(60):
                state = fly(autopilot, model, state, heading, 1.0, CONTROL_DT)
                assert autopilot._helm_angle == pytest.approx(state.helm_angle, abs=1e-9)

    def test_the_thrust_waits_while_the_helm_crosses_to_the_other_side(self):
        _, dynamics, autopilot, model = setup("30m", "vectored_thrust")
        state = fly(autopilot, model, AT_REST, 1.0, 1.0, 10.0)
        assert state.helm_angle == pytest.approx(-dynamics.steering_max_angle), "hard over to port for a turn at next to no speed"
        full = autopilot.command(1.0, 1.0, HullObservation(state.heading, state.surge, state.yaw_rate), CONTROL_DT)
        autopilot_before = (autopilot._astern, autopilot._helm_angle)
        held = autopilot.command(state.heading - 1.0, 1.0, HullObservation(state.heading, state.surge, state.yaw_rate), CONTROL_DT)
        assert autopilot_before[1] < 0.0 < held.helm_angle, "the helm is sent to starboard"
        assert full.thrusts[0] > 0.1 * dynamics.max_thrust
        assert (
            0.0 < held.thrusts[0] <= dynamics.max_thrust * math.sin(HELM_CROSSING_SHARE * dynamics.steering_max_angle) / math.sin(dynamics.steering_max_angle) * (1 + 1e-9)
        ), "with little thrust while it is still to port"
        assert held.yaw_saturated and held.surge_saturated

    def test_a_turn_at_rest_pushes_the_hull_ahead(self):
        """Vectored thrust turns by its thrust: yaw has priority and the vessel gains speed it was not asked for."""
        vessel, _, autopilot, model = setup("30m", "vectored_thrust")
        states = []
        fly(autopilot, model, AT_REST, math.pi / 2, 0.0, 20.0, states=states)
        assert states[-1].heading > 0.3 and max(state.surge for state in states) > 0.5

    def test_astern_and_ahead_do_not_alternate_in_a_turn(self):
        """Going astern or back ahead sends the helm across: it happens a few times in a manoeuvre, not every other step."""
        _, _, autopilot, model, state, cruise = cruising("30m", "vectored_thrust")
        commands = []
        fly(autopilot, model, state, math.pi / 2, 0.2 * cruise, 150.0, commands)
        thrusts = [command.thrusts[0] for command in commands]
        reversals = sum(1 for before, after in zip(thrusts, thrusts[1:]) if before * after < 0.0)
        assert min(thrusts) < 0.0 < max(thrusts)
        assert reversals <= 6


class TestLimits:
    def test_thrust_stays_within_the_thruster_limits(self):
        _, dynamics, autopilot, model = setup("5m")
        commands = []
        fly(autopilot, model, AT_REST, math.pi, 4.0, 30.0, commands)
        for command in commands:
            assert abs(command.thrusts[0]) <= dynamics.max_thrust + 1e-9
            assert abs(command.thrusts[1]) <= dynamics.max_thrust + 1e-9
            assert command.helm_angle is None
        assert any(command.yaw_saturated for command in commands), "a half turn from rest saturates the yaw"

    def test_yaw_has_priority_over_surge(self):
        autopilot = setup("5m")[2]
        command = autopilot.command(math.pi / 2, 4.0, HullObservation(0.0, 0.0, 0.0), CONTROL_DT)
        assert command.yaw_saturated
        assert command.thrusts[0] == pytest.approx(-command.thrusts[1]), "the whole thrust goes to the differential"

    @pytest.mark.parametrize("steering", ["skid", *HELM_TYPES])
    def test_integrators_hold_while_their_loop_saturates(self, steering):
        """Anti-windup: an unreachable speed does not wind the speed integral up."""
        _, dynamics, autopilot, model = setup("5m", steering)
        autopilot.gains = dataclasses.replace(autopilot.gains, max_speed=100.0, max_acceleration=100.0)
        fly(autopilot, model, AT_REST, 0.0, 100.0, 60.0)
        held = autopilot._speed_integral
        fly(autopilot, model, AT_REST, 0.0, 100.0, 60.0)
        assert autopilot._speed_integral == pytest.approx(held, abs=1e-6)


@pytest.mark.parametrize("steering", ["skid", *HELM_TYPES])
def test_reset_clears_the_integrators_and_restarts_the_speed_reference(steering):
    _, _, autopilot, model = setup("5m", steering)
    fly(autopilot, model, AT_REST, 1.0, 3.0, 20.0)
    autopilot.reset(2.0)
    assert autopilot._rate_integral == 0.0 and autopilot._speed_integral == 0.0
    assert autopilot._speed_reference == 2.0
    assert autopilot._helm_angle == 0.0 and autopilot._astern is False and autopilot._previous_rate_demand is None


@pytest.mark.parametrize("steering", HELM_TYPES)
def test_the_turn_rate_demand_builds_up_instead_of_jumping(steering):
    """A helm cannot follow a jump: the demand grows at the yaw acceleration the heading approach plans with."""
    _, _, autopilot, _ = setup("30m", steering)
    gains = autopilot.gains
    hull = HullObservation(0.0, gains.steering_speed, 0.0)
    autopilot.reset(gains.steering_speed)
    demands = []
    for _ in range(5):
        autopilot.command(math.pi / 2, gains.steering_speed, hull, CONTROL_DT)
        demands.append(autopilot._previous_rate_demand)
    step = gains.heading_deceleration * CONTROL_DT
    assert demands == pytest.approx([step * (index + 1) for index in range(5)])
    autopilot.command(-math.pi / 2, gains.steering_speed, hull, CONTROL_DT)
    assert autopilot._previous_rate_demand == pytest.approx(-step), "a reversal drops the old turn at once and builds up the new one"
    skid = setup("30m")[2]
    skid.command(math.pi / 2, 8.0, HullObservation(0.0, 8.0, 0.0), CONTROL_DT)
    assert skid._previous_rate_demand == skid.gains.max_turn_rate, "the skid steered hull's demand jumps, as before"
