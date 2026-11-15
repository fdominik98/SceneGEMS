"""Actuator allocation: a surge force and a yaw moment as the thrusts and the helm angle of each steering type, within their limits."""

import math

import pytest

from scenegems_tool.vessel_stack.control_layers.custom.actuator_allocation import (
    HELM_CROSSING_SHARE,
    REVERSE_ENTRY_SHARE,
    RUDDER_PEAK_ANGLE,
    ActuatorCommand,
    allocate_rudder,
    allocate_skid,
    allocate_vectored_thrust,
    helm_travel,
    rudder_attack_angle,
    wait_for_helm,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import rudder_force, rudder_normal_force_coefficient, vectored_thrust_force

MAX_THRUST = 1000.0
STEERING_X = -10.0  # the helm's side force acts 10 m aft of midship
MAX_ANGLE = math.radians(30.0)
RUDDER_AREA, LIFT_SLOPE = 2.0, 2.5
RUDDER_GAIN = -rudder_normal_force_coefficient(RUDDER_AREA, LIFT_SLOPE)  # one half rho times area times lift slope
RUDDER_MAX_ANGLE = math.radians(35.0)
SPEED_FLOOR = 0.5


def rudder(force, moment, surge, sway_at_rudder=0.0, max_angle=RUDDER_MAX_ANGLE) -> ActuatorCommand:
    return allocate_rudder(force, moment, surge, sway_at_rudder, max_thrust=MAX_THRUST, steering_x=STEERING_X, max_angle=max_angle, force_gain=RUDDER_GAIN, speed_floor=SPEED_FLOOR)


def vectored(force, moment, astern=False) -> ActuatorCommand:
    return allocate_vectored_thrust(force, moment, max_thrust=MAX_THRUST, steering_x=STEERING_X, max_angle=MAX_ANGLE, astern=astern)


def rudder_moment(command: ActuatorCommand, surge: float, sway_at_rudder: float = 0.0) -> float:
    """The yaw moment the model's rudder gives at the commanded angle (generators/hydrodynamics.rudder_force)."""
    return STEERING_X * rudder_force(command.helm_angle, surge, sway_at_rudder, RUDDER_AREA, LIFT_SLOPE)[1]


def vectored_force_and_moment(command: ActuatorCommand):
    """The surge force and yaw moment the model's thruster gives at the commanded angle and thrust."""
    x, y = vectored_thrust_force(command.helm_angle, command.thrusts[0])
    return x, STEERING_X * y


class TestSkid:
    def skid(self, force, moment) -> ActuatorCommand:
        return allocate_skid(force, moment, max_thrust=MAX_THRUST, thruster_arm=2.0)

    def test_the_thrusts_give_the_force_and_the_moment(self):
        command = self.skid(600.0, 800.0)
        port, starboard = command.thrusts
        assert port + starboard == pytest.approx(600.0)
        assert 2.0 * (starboard - port) == pytest.approx(800.0), "the starboard thruster turns the hull to port"
        assert command.helm_angle is None
        assert (command.force, command.moment) == (600.0, 800.0)
        assert not command.yaw_saturated and not command.surge_saturated

    def test_yaw_comes_first_and_the_common_thrust_gets_the_rest(self):
        command = self.skid(1500.0, 3000.0)  # the differential takes 1500 of the 2000 N
        port, starboard = command.thrusts
        assert starboard - port == pytest.approx(1500.0)
        assert port + starboard == pytest.approx(500.0)
        assert command.surge_saturated and not command.yaw_saturated
        assert command.force == pytest.approx(500.0) and command.moment == 3000.0

    def test_a_moment_beyond_full_differential_thrust_saturates_the_yaw(self):
        command = self.skid(500.0, -9000.0)
        assert command.thrusts == (MAX_THRUST, -MAX_THRUST)
        assert command.yaw_saturated and command.surge_saturated
        assert command.moment == pytest.approx(-4000.0) and command.force == 0.0

    def test_every_thrust_stays_within_the_thruster(self):
        for force in (-5000.0, -300.0, 0.0, 700.0, 5000.0):
            for moment in (-9000.0, -100.0, 0.0, 2500.0, 9000.0):
                assert all(abs(thrust) <= MAX_THRUST for thrust in self.skid(force, moment).thrusts)


class TestRudderAttackAngle:
    @pytest.mark.parametrize("angle_deg", [-35.0, -20.0, -3.0, 0.0, 0.5, 12.0, 30.0, 35.2])
    def test_it_inverts_the_side_force_of_the_angle(self, angle_deg):
        angle = math.radians(angle_deg)
        assert rudder_attack_angle(math.sin(angle) * math.cos(angle) ** 2) == pytest.approx(angle, abs=1e-6)

    def test_beyond_the_peak_it_stays_at_the_peak(self):
        """sin(a) cos(a)^2 is largest at tan(a)^2 = 1/2, about 35.3 degrees: more angle would give less force."""
        assert rudder_attack_angle(10.0) == pytest.approx(RUDDER_PEAK_ANGLE)
        assert rudder_attack_angle(-10.0) == pytest.approx(-RUDDER_PEAK_ANGLE)
        assert math.degrees(RUDDER_PEAK_ANGLE) == pytest.approx(35.264, abs=1e-3)


class TestRudder:
    def test_the_thrust_is_the_surge_force(self):
        command = rudder(700.0, 0.0, 4.0)
        assert command.thrusts == (700.0,) and command.helm_angle == 0.0
        assert not command.surge_saturated and command.force == 700.0

    @pytest.mark.parametrize("force", [5000.0, -5000.0])
    def test_the_thrust_stays_within_the_thruster_both_ways(self, force):
        command = rudder(force, 0.0, 4.0)
        assert command.thrusts == (math.copysign(MAX_THRUST, force),)
        assert command.surge_saturated and command.force == math.copysign(MAX_THRUST, force)

    @pytest.mark.parametrize("moment", [-3000.0, -500.0, 800.0, 4000.0])
    @pytest.mark.parametrize("surge", [1.0, 4.0, 9.0])
    def test_the_helm_angle_gives_the_moment_on_the_models_rudder(self, moment, surge):
        command = rudder(0.0, moment, surge)
        if not command.yaw_saturated:
            assert rudder_moment(command, surge) == pytest.approx(moment, rel=1e-9)
            assert command.moment == moment
        else:
            assert abs(command.helm_angle) == pytest.approx(RUDDER_MAX_ANGLE)

    def test_a_positive_moment_takes_a_negative_helm_angle(self):
        """A positive moment turns the vessel to port, a positive helm angle to starboard."""
        assert rudder(0.0, 800.0, 4.0).helm_angle < 0.0
        assert rudder(0.0, -800.0, 4.0).helm_angle > 0.0
        assert rudder(0.0, 800.0, 4.0).helm_angle == -rudder(0.0, -800.0, 4.0).helm_angle

    def test_the_same_moment_takes_less_helm_at_more_speed(self):
        assert abs(rudder(0.0, 800.0, 8.0).helm_angle) < abs(rudder(0.0, 800.0, 4.0).helm_angle)
        assert rudder(0.0, 800.0, 8.0).helm_angle == pytest.approx(rudder(0.0, 200.0, 4.0).helm_angle), "the force follows the speed squared"

    def test_the_helm_goes_hard_over_for_more_than_the_rudder_gives(self):
        full = abs(STEERING_X) * RUDDER_GAIN * 4.0**2 * math.sin(RUDDER_MAX_ANGLE) * math.cos(RUDDER_MAX_ANGLE) ** 2
        command = rudder(0.0, 1.5 * full, 4.0)
        assert command.helm_angle == pytest.approx(-RUDDER_MAX_ANGLE)
        assert command.yaw_saturated
        assert command.moment == pytest.approx(full), "the moment it gives is the rudder's hard over"
        assert not rudder(0.0, 0.9 * full, 4.0).yaw_saturated

    def test_a_helm_limit_beyond_the_peak_is_not_used(self):
        """With a limit of 45 degrees the helm still stops at the angle of the largest side force."""
        command = rudder(0.0, 1e9, 4.0, max_angle=math.radians(45.0))
        assert command.helm_angle == pytest.approx(-RUDDER_PEAK_ANGLE) and command.yaw_saturated

    def test_the_helm_angle_never_goes_beyond_hard_over(self):
        """Whatever the moment, the speed and the drift at the stern: the model's helm has its stops just beyond hard over."""
        for moment in (-1e9, -4000.0, -300.0, 0.0, 300.0, 4000.0, 1e9):
            for surge in (-9.0, -0.6, -0.1, 0.0, 0.1, 0.6, 4.0, 9.0):
                for sway_at_rudder in (-5.0, -0.6, 0.0, 0.6, 5.0):
                    command = rudder(700.0, moment, surge, sway_at_rudder)
                    assert abs(command.helm_angle) <= RUDDER_MAX_ANGLE, (moment, surge, sway_at_rudder)
                    if abs(command.helm_angle) == RUDDER_MAX_ANGLE:
                        assert command.yaw_saturated

    @pytest.mark.parametrize("surge", [0.0, 1e-9, -1e-9, 0.3, -0.3])
    def test_within_the_speed_floor_the_flow_counts_as_the_floor_speed_ahead(self, surge):
        """No division by zero at rest: the helm takes the angle of the floor speed, the way that turns right once the vessel moves ahead."""
        command = rudder(0.0, 50.0, surge)
        assert command.helm_angle == rudder(0.0, 50.0, SPEED_FLOOR).helm_angle
        assert -RUDDER_MAX_ANGLE < command.helm_angle < 0.0

    def test_at_rest_a_moment_the_rudder_cannot_give_saturates_the_yaw(self):
        command = rudder(0.0, 5000.0, 0.0)
        assert command.helm_angle == pytest.approx(-RUDDER_MAX_ANGLE)
        assert command.yaw_saturated
        assert command.moment == pytest.approx(rudder_moment(command, SPEED_FLOOR)), "what the rudder would give hard over at the floor speed"
        assert 0.0 < command.moment < 5000.0

    def test_astern_the_helm_goes_the_other_way(self):
        """The flow comes from aft, so the same helm angle pushes the stern the other way."""
        ahead, astern = rudder(0.0, 300.0, 4.0), rudder(0.0, 300.0, -4.0)
        assert astern.helm_angle == pytest.approx(-ahead.helm_angle)
        assert rudder_moment(astern, -4.0) == pytest.approx(300.0)

    def test_the_helm_angle_follows_the_flow_at_the_rudder(self):
        """In a turn to port the stern swings to starboard: the flow meets the rudder from port, and the helm goes further to port for the same moment."""
        straight = rudder(0.0, 500.0, 4.0)
        turning = rudder(0.0, 500.0, 4.0, sway_at_rudder=-0.6)
        attack = rudder_attack_angle(500.0 / STEERING_X / (RUDDER_GAIN * (4.0**2 + 0.6**2)))
        assert turning.helm_angle == pytest.approx(attack + math.atan(-0.6 / 4.0)), "the angle of attack for the side force plus the drift of the flow"
        assert turning.helm_angle < straight.helm_angle < 0.0
        assert rudder_moment(turning, 4.0, -0.6) == pytest.approx(500.0, rel=0.1), "close to the moment in the drifting flow"
        assert rudder_moment(straight, 4.0, -0.6) < 0.5 * 500.0, "the straight-course angle would give less than half of it"

    def test_a_drift_beyond_the_helms_limit_saturates_the_yaw(self):
        command = rudder(0.0, 150000.0, 4.0, sway_at_rudder=-2.0)
        assert command.helm_angle == pytest.approx(-RUDDER_MAX_ANGLE) and command.yaw_saturated
        assert command.moment == pytest.approx(rudder_moment(command, 4.0, -2.0))


class TestVectoredThrust:
    def test_thrust_and_angle_give_the_force_and_the_moment(self):
        command = vectored(600.0, 2000.0)  # a side force of -200 N at the stern
        assert command.thrusts[0] == pytest.approx(math.hypot(600.0, 200.0))
        assert command.helm_angle == pytest.approx(math.atan2(-200.0, 600.0))
        force, moment = vectored_force_and_moment(command)
        assert (force, moment) == (pytest.approx(600.0), pytest.approx(2000.0))
        assert (command.force, command.moment) == (600.0, 2000.0)
        assert not command.yaw_saturated and not command.surge_saturated

    def test_a_positive_moment_takes_a_negative_helm_angle(self):
        assert vectored(600.0, 2000.0).helm_angle < 0.0 < vectored(600.0, -2000.0).helm_angle

    def test_no_force_and_no_moment_is_no_thrust(self):
        command = vectored(0.0, 0.0)
        assert command.thrusts == (0.0,) and command.helm_angle == 0.0

    def test_when_the_helms_limit_binds_the_thrust_is_what_the_side_force_needs(self):
        """Yaw has priority: the vessel gets the moment and more surge force than wanted."""
        command = vectored(100.0, 4000.0)  # a side force of 400 N would need 76 degrees at 412 N
        assert command.helm_angle == pytest.approx(-MAX_ANGLE)
        assert command.thrusts[0] == pytest.approx(400.0 / math.sin(MAX_ANGLE))
        force, moment = vectored_force_and_moment(command)
        assert moment == pytest.approx(4000.0) and force == pytest.approx(400.0 / math.tan(MAX_ANGLE))
        assert command.surge_saturated and not command.yaw_saturated
        assert command.force == pytest.approx(force) and command.moment == 4000.0

    def test_a_turn_at_rest_needs_thrust(self):
        command = vectored(0.0, 3000.0)
        assert command.helm_angle == pytest.approx(-MAX_ANGLE) and command.thrusts[0] == pytest.approx(600.0)

    def test_a_force_beyond_the_thruster_keeps_the_moment(self):
        """The thrust limit binds within the helm's limit: the angle grows so the side force stays, the surge force gets the rest."""
        command = vectored(5000.0, 2000.0)
        assert command.thrusts == (MAX_THRUST,)
        force, moment = vectored_force_and_moment(command)
        assert moment == pytest.approx(2000.0)
        assert force == pytest.approx(math.sqrt(MAX_THRUST**2 - 200.0**2))
        assert command.surge_saturated and not command.yaw_saturated and command.force == pytest.approx(force)

    def test_a_moment_beyond_full_thrust_hard_over_saturates_the_yaw(self):
        command = vectored(200.0, 9000.0)
        assert command.thrusts == (MAX_THRUST,) and command.helm_angle == pytest.approx(-MAX_ANGLE)
        assert command.yaw_saturated and command.surge_saturated
        assert command.moment == pytest.approx(abs(STEERING_X) * MAX_THRUST * math.sin(MAX_ANGLE))

    def test_thrust_and_angle_stay_within_their_limits(self):
        for force in (-5000.0, -300.0, -1.0, 0.0, 1.0, 700.0, 5000.0):
            for moment in (-20000.0, -900.0, -1.0, 0.0, 1.0, 2500.0, 20000.0):
                for astern in (False, True):
                    command = vectored(force, moment, astern)
                    assert abs(command.thrusts[0]) <= MAX_THRUST and abs(command.helm_angle) <= MAX_ANGLE
                    given_force, given_moment = vectored_force_and_moment(command)
                    assert command.force == pytest.approx(given_force, abs=1e-9) and command.moment == pytest.approx(given_moment, abs=1e-9)
                    assert given_moment * moment >= 0.0, "the moment never turns the vessel the wrong way"


class TestVectoredThrustBraking:
    def test_braking_straight_reverses_the_thrust(self):
        command = vectored(-600.0, 0.0)
        assert command.thrusts == (-600.0,) and command.helm_angle == 0.0
        assert not command.surge_saturated

    def test_astern_the_helm_gives_the_moment_from_the_mirrored_angle(self):
        """Reversed thrust pushes the stern the other way: a turn to port takes a positive helm angle."""
        command = vectored(-600.0, 300.0)  # a side force of -30 N, well within the entry angle
        assert command.thrusts[0] == pytest.approx(-math.hypot(600.0, 30.0))
        assert command.helm_angle == pytest.approx(math.atan2(30.0, 600.0)) and command.helm_angle > 0.0
        force, moment = vectored_force_and_moment(command)
        assert (force, moment) == (pytest.approx(-600.0), pytest.approx(300.0))
        assert not command.yaw_saturated and not command.surge_saturated

    def test_a_turn_keeps_the_thrust_ahead_when_it_would_take_much_helm_astern(self):
        """Beyond the entry angle the thruster does not go astern: the helm goes hard over ahead and the vessel does not brake."""
        side = 600.0 * math.tan(REVERSE_ENTRY_SHARE * MAX_ANGLE) * 1.05
        command = vectored(-600.0, 10.0 * side)  # a side force of -side at the stern
        assert command.thrusts[0] == pytest.approx(side / math.sin(MAX_ANGLE)) and command.thrusts[0] > 0.0
        assert command.helm_angle == pytest.approx(-MAX_ANGLE)
        assert command.surge_saturated and command.force > 0.0, "it says that the surge force it gives is ahead"
        assert not command.yaw_saturated and vectored_force_and_moment(command)[1] == pytest.approx(10.0 * side)

    def test_a_thruster_running_astern_stays_astern_within_the_helms_limit(self):
        """Entry and exit differ, so the thruster does not go back and forth at one boundary."""
        side = 600.0 * math.tan(0.8 * MAX_ANGLE)
        moment = 10.0 * side
        assert vectored(-600.0, moment, astern=False).thrusts[0] > 0.0
        staying = vectored(-600.0, moment, astern=True)
        assert staying.thrusts[0] < 0.0 and staying.helm_angle == pytest.approx(0.8 * MAX_ANGLE)
        assert vectored_force_and_moment(staying) == (pytest.approx(-600.0), pytest.approx(moment))
        assert vectored(-600.0, 10.0 * 600.0 * math.tan(MAX_ANGLE) * 1.01, astern=True).thrusts[0] > 0.0, "beyond the helm's limit it goes back ahead"

    def test_a_thruster_running_astern_goes_ahead_for_a_force_ahead(self):
        assert vectored(1.0, 0.0, astern=True).thrusts[0] > 0.0

    def test_braking_beyond_the_thruster_is_limited(self):
        command = vectored(-5000.0, 0.0)
        assert command.thrusts == (-MAX_THRUST,) and command.surge_saturated and command.force == pytest.approx(-MAX_THRUST)


class TestHelmTravel:
    def test_the_helm_moves_toward_the_commanded_angle_by_at_most_its_travel(self):
        assert helm_travel(0.0, 0.5, 0.1) == pytest.approx(0.1)
        assert helm_travel(0.2, -0.5, 0.1) == pytest.approx(0.1)
        assert helm_travel(0.45, 0.5, 0.1) == 0.5, "it stops on the commanded angle"

    def command(self, thrust=800.0, helm=-0.4) -> ActuatorCommand:
        return ActuatorCommand(thrusts=(thrust,), helm_angle=helm, force=700.0, moment=3000.0, yaw_saturated=False, surge_saturated=False)

    def wait(self, command, helm_angle) -> ActuatorCommand:
        return wait_for_helm(command, helm_angle, steering_x=STEERING_X, max_angle=MAX_ANGLE)

    @pytest.mark.parametrize("helm_angle", [-0.5, -0.4, -0.01, 0.0, HELM_CROSSING_SHARE * MAX_ANGLE])
    def test_a_helm_on_the_commanded_side_or_nearly_across_gets_the_full_thrust(self, helm_angle):
        assert self.wait(self.command(), helm_angle) is self.command() or self.wait(self.command(), helm_angle) == self.command()

    def test_a_helm_far_on_the_other_side_holds_the_thrust_back(self):
        """Hard over to starboard with a command to port: the thrust would turn the vessel to starboard until the helm is across."""
        held = self.wait(self.command(), MAX_ANGLE)
        tolerance = HELM_CROSSING_SHARE * MAX_ANGLE
        assert held.thrusts[0] == pytest.approx(800.0 * math.sin(tolerance) / math.sin(MAX_ANGLE))
        assert held.helm_angle == -0.4, "the helm is still sent across"
        assert held.yaw_saturated and held.surge_saturated
        assert held.moment == pytest.approx(STEERING_X * held.thrusts[0] * math.sin(MAX_ANGLE)) and held.moment < 0.0, "the little it gives is the wrong way, and it says so"
        assert abs(held.moment) == pytest.approx(abs(STEERING_X) * 800.0 * math.sin(tolerance)), "the wrong-way side force is that of the full thrust at the tolerance"

    def test_the_thrust_comes_back_as_the_helm_crosses(self):
        thrusts = [self.wait(self.command(), angle).thrusts[0] for angle in (0.5, 0.3, 0.1, 0.05, 0.0, -0.2)]
        assert thrusts == sorted(thrusts) and thrusts[-1] == 800.0 and thrusts[0] < 0.1 * 800.0

    def test_reversed_thrust_waits_for_the_helm_as_well(self):
        """Going astern in a turn: the helm must cross to the mirrored side first."""
        held = self.wait(self.command(thrust=-800.0, helm=0.2), -MAX_ANGLE)
        assert -800.0 < held.thrusts[0] < 0.0 and held.yaw_saturated

    def test_a_command_without_a_helm_passes(self):
        skid = allocate_skid(100.0, 100.0, max_thrust=MAX_THRUST, thruster_arm=2.0)
        assert self.wait(skid, 0.3) is skid
