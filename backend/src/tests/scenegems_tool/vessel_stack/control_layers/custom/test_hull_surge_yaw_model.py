"""HullSurgeYawModel: the generated hull's design points hold in the horizontal-plane model, for each steering type."""

import dataclasses
import math

import pytest

from scenegems_tool.vessel_stack.calibration.reference_scenarios import scaled_vessel
from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel, damping
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import derive_vessel_dynamics

AT_REST = HullState(x=0.0, y=0.0, heading=0.0, surge=0.0, sway=0.0, yaw_rate=0.0)
HELM_TYPES = ("rudder", "vectored_thrust")


@pytest.fixture(params=["5m", "30m"])
def hull(request):
    vessel = scaled_vessel(request.param)
    dynamics = derive_vessel_dynamics(vessel, 0.0, {})
    return dynamics, HullSurgeYawModel(dynamics)


@pytest.fixture(params=[(scale, steering) for scale in ("5m", "30m", "100m") for steering in HELM_TYPES], ids=lambda param: f"{param[0]}-{param[1]}")
def helm_hull(request):
    """A hull with one thruster and a helm: a small, a middle and a large vessel with a rudder and with vectored thrust."""
    scale, steering = request.param
    vessel = dataclasses.replace(scaled_vessel(scale), _steering_type=steering)
    dynamics = derive_vessel_dynamics(vessel, 0.0, {})
    return dynamics, HullSurgeYawModel(dynamics)


def run(model, state, port, starboard, seconds, dt=0.01):
    for _ in range(int(round(seconds / dt))):
        state = model.step(state, (port, starboard), None, dt)
    return state


def steer(model, state, thrust, helm_angle, seconds, dt=0.01):
    for _ in range(int(round(seconds / dt))):
        state = model.step(state, (thrust,), helm_angle, dt)
    return state


def test_damping_opposes_the_velocity_both_ways():
    assert damping(-2.0, -3.0, 2.0) == pytest.approx(16.0)
    assert damping(-2.0, -3.0, -2.0) == pytest.approx(-16.0)


def test_full_thrust_settles_at_the_design_speed(hull):
    dynamics, model = hull
    state = run(model, AT_REST, dynamics.max_thrust, dynamics.max_thrust, 600.0)
    assert state.surge == pytest.approx(dynamics.design_speed, rel=1e-3)
    assert state.heading == 0.0 and state.y == 0.0


def test_full_differential_thrust_settles_at_the_design_yaw_rate(hull):
    dynamics, model = hull
    state = run(model, AT_REST, -dynamics.max_thrust, dynamics.max_thrust, 200.0)
    assert state.yaw_rate == pytest.approx(dynamics.design_yaw_rate, rel=1e-3)


def test_the_starboard_thruster_turns_the_hull_to_port(hull):
    """Port is +y, so more thrust to starboard turns counterclockwise, as headings count."""
    dynamics, model = hull
    state = run(model, AT_REST, 0.0, dynamics.max_thrust, 5.0)
    assert state.yaw_rate > 0 and state.heading > 0


def test_thrust_is_limited_to_the_thruster_maximum(hull):
    dynamics, model = hull
    capped = run(model, AT_REST, 10 * dynamics.max_thrust, 10 * dynamics.max_thrust, 1.0)
    full = run(model, AT_REST, dynamics.max_thrust, dynamics.max_thrust, 1.0)
    assert capped == full


def test_the_pose_follows_the_heading(hull):
    dynamics, model = hull
    north = HullState(x=0.0, y=0.0, heading=math.pi / 2, surge=1.0, sway=0.0, yaw_rate=0.0)
    state = model.step(north, (0.0, 0.0), None, 0.1)
    assert state.x == pytest.approx(0.0, abs=1e-12)
    assert state.y > 0


def test_a_skid_steered_hull_has_no_helm(hull):
    dynamics, model = hull
    assert run(model, AT_REST, dynamics.max_thrust, 0.0, 5.0).helm_angle == 0.0
    with pytest.raises(ValueError, match="has no helm"):
        model.step(AT_REST, (0.0, 0.0), 0.1, 0.1)
    with pytest.raises(ValueError, match="takes 2 thrusts, got 1"):
        model.step(AT_REST, (0.0,), None, 0.1)


class TestHelm:
    def test_full_thrust_settles_at_the_design_speed(self, helm_hull):
        dynamics, model = helm_hull
        state = steer(model, AT_REST, dynamics.max_thrust, 0.0, 900.0, dt=0.02)
        assert state.surge == pytest.approx(dynamics.design_speed, rel=1e-3)
        assert state.heading == 0.0 and state.y == 0.0 and state.helm_angle == 0.0

    def test_the_helm_hard_over_at_the_steering_speed_settles_near_the_max_steady_yaw_rate(self, helm_hull):
        """The calibration point of the hull's yaw damping: the steering thrust, the helm hard over to port."""
        dynamics, model = helm_hull
        cruising = HullState(0.0, 0.0, 0.0, dynamics.steering_speed, 0.0, 0.0)
        seconds = max(300.0, 25.0 / dynamics.max_steady_yaw_rate)  # the surge speed settles last: several circles
        state = steer(model, cruising, dynamics.steering_thrust, -dynamics.steering_max_angle, seconds, dt=0.05)
        assert state.yaw_rate == pytest.approx(dynamics.max_steady_yaw_rate, rel=1e-3)
        assert dynamics.max_steady_yaw_rate <= dynamics.design_yaw_rate * (1.0 + 1e-9)
        assert state.sway < 0.0, "the hull slides outward, to starboard in a turn to port"
        assert 0.0 < state.surge < dynamics.steering_speed, "and the turn slows it down"

    def test_a_positive_helm_angle_turns_the_hull_to_starboard(self, helm_hull):
        dynamics, model = helm_hull
        cruising = HullState(0.0, 0.0, 0.0, dynamics.steering_speed, 0.0, 0.0)
        to_starboard = steer(model, cruising, dynamics.steering_thrust, 0.5 * dynamics.steering_max_angle, 10.0)
        to_port = steer(model, cruising, dynamics.steering_thrust, -0.5 * dynamics.steering_max_angle, 10.0)
        assert to_starboard.yaw_rate < 0 and to_starboard.heading < 0
        assert to_port.yaw_rate == pytest.approx(-to_starboard.yaw_rate) and to_port.heading == pytest.approx(-to_starboard.heading)

    def test_the_helm_travels_at_the_steering_rate_and_stops_on_the_commanded_angle(self, helm_hull):
        dynamics, model = helm_hull
        target = 0.6 * dynamics.steering_max_angle
        travel_s = target / dynamics.steering_rate
        halfway = steer(model, AT_REST, 0.0, target, 0.5 * travel_s, dt=travel_s / 200.0)
        assert halfway.helm_angle == pytest.approx(0.5 * target, rel=1e-6)
        arrived = steer(model, AT_REST, 0.0, target, 2.0 * travel_s, dt=travel_s / 200.0)
        assert arrived.helm_angle == pytest.approx(target, abs=1e-12)
        back = steer(model, arrived, 0.0, -target, 0.5 * travel_s, dt=travel_s / 200.0)
        assert back.helm_angle == pytest.approx(0.5 * target, rel=1e-6), "a quarter of the way from one side to the other"

    def test_the_helm_stops_at_hard_over(self, helm_hull):
        dynamics, model = helm_hull
        state = steer(model, AT_REST, 0.0, 10.0, 3.0 * dynamics.steering_max_angle / dynamics.steering_rate)
        assert state.helm_angle == pytest.approx(dynamics.steering_max_angle)

    def test_the_forces_act_where_the_helm_is_not_where_it_is_commanded(self, helm_hull):
        """Within the first step the helm is still amidships: thrust straight ahead, no turn yet."""
        dynamics, model = helm_hull
        cruising = HullState(0.0, 0.0, 0.0, dynamics.steering_speed, 0.0, 0.0)
        state = model.step(cruising, (dynamics.steering_thrust,), dynamics.steering_max_angle, 0.01)
        assert state.yaw_rate == 0.0 and state.helm_angle == pytest.approx(dynamics.steering_rate * 0.01)

    def test_thrust_is_limited_to_the_thruster_maximum(self, helm_hull):
        dynamics, model = helm_hull
        assert steer(model, AT_REST, 10 * dynamics.max_thrust, 0.0, 1.0) == steer(model, AT_REST, dynamics.max_thrust, 0.0, 1.0)
        assert steer(model, AT_REST, -10 * dynamics.max_thrust, 0.0, 1.0).surge < 0.0, "and it reverses"

    def test_a_hull_with_a_helm_needs_one_thrust_and_a_helm_angle(self, helm_hull):
        _, model = helm_hull
        with pytest.raises(ValueError, match="needs a helm angle"):
            model.step(AT_REST, (0.0,), None, 0.1)
        with pytest.raises(ValueError, match="takes 1 thrusts, got 2"):
            model.step(AT_REST, (0.0, 0.0), 0.0, 0.1)


@pytest.mark.parametrize("scale", ["5m", "30m"])
class TestSteeringGear:
    def hull(self, scale, steering):
        dynamics = derive_vessel_dynamics(dataclasses.replace(scaled_vessel(scale), _steering_type=steering), 0.0, {})
        return dynamics, HullSurgeYawModel(dynamics)

    def test_a_rudder_does_nothing_at_rest_and_needs_no_thrust_under_way(self, scale):
        """A rudder is a foil in the flow past the stern: no speed, no force (the propeller's wash is not modelled)."""
        dynamics, model = self.hull(scale, "rudder")
        hard_over = dataclasses.replace(AT_REST, helm_angle=-dynamics.steering_max_angle)
        assert model.step(hard_over, (0.0,), -dynamics.steering_max_angle, 0.1).yaw_rate == 0.0
        coasting = dataclasses.replace(hard_over, surge=dynamics.steering_speed)
        assert model.step(coasting, (0.0,), -dynamics.steering_max_angle, 0.1).yaw_rate > 0.0

    def test_a_rudder_turns_harder_the_faster_the_hull_goes(self, scale):
        dynamics, model = self.hull(scale, "rudder")
        rates = []
        for share in (0.5, 1.0, 2.0):
            state = HullState(0.0, 0.0, 0.0, share * dynamics.steering_speed, 0.0, 0.0, helm_angle=-0.2)
            rates.append(model.step(state, (0.0,), -0.2, 0.01).yaw_rate)
        assert rates[1] == pytest.approx(4.0 * rates[0]) and rates[2] == pytest.approx(4.0 * rates[1]), "the force follows the speed squared"

    def test_a_rudder_slows_the_hull_down(self, scale):
        dynamics, model = self.hull(scale, "rudder")
        straight = HullState(0.0, 0.0, 0.0, dynamics.steering_speed, 0.0, 0.0)
        turned = dataclasses.replace(straight, helm_angle=dynamics.steering_max_angle)
        assert model.step(turned, (0.0,), dynamics.steering_max_angle, 0.01).surge < model.step(straight, (0.0,), 0.0, 0.01).surge

    def test_vectored_thrust_turns_at_rest_and_not_without_thrust(self, scale):
        dynamics, model = self.hull(scale, "vectored_thrust")
        hard_over = dataclasses.replace(AT_REST, helm_angle=-dynamics.steering_max_angle)
        pushed = model.step(hard_over, (dynamics.max_thrust,), -dynamics.steering_max_angle, 0.1)
        assert pushed.yaw_rate > 0.0 and pushed.surge > 0.0 and pushed.sway < 0.0, "the thrust pushes the stern to starboard"
        coasting = dataclasses.replace(hard_over, surge=dynamics.steering_speed)
        assert model.step(coasting, (0.0,), -dynamics.steering_max_angle, 0.1).yaw_rate == 0.0

    def test_reversed_vectored_thrust_turns_the_other_way(self, scale):
        dynamics, model = self.hull(scale, "vectored_thrust")
        hard_over = dataclasses.replace(AT_REST, helm_angle=-dynamics.steering_max_angle)
        ahead = model.step(hard_over, (dynamics.max_thrust,), -dynamics.steering_max_angle, 0.1)
        astern = model.step(hard_over, (-dynamics.max_thrust,), -dynamics.steering_max_angle, 0.1)
        assert astern.yaw_rate == pytest.approx(-ahead.yaw_rate) and astern.surge == pytest.approx(-ahead.surge)
