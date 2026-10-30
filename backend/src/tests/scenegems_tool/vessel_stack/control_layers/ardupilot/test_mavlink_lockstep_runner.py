"""The MAVLink lockstep runner against fake SITL vessels: stepping on SITL time, alignment, validation, run records."""

import numpy as np
import pytest

from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.asv_software.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.contracts.clock import derive_seed
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import MavlinkLinkError
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import (
    DEFAULT_LOCKSTEP_DT_S,
    GUIDED_CHECK_MS,
    START_QUANTUM_S,
    lockstep_dt,
    mavlink_instance,
    mavlink_replay_instance,
    run_mavlink_lockstep,
    run_mavlink_stack,
)
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver, StackUnavailableError
from tests.scenegems_tool.vessel_stack.control_layers.ardupilot.fake_sitl import FakeLink, StuckLink
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, straight_trajectories


def build_run(trajectories, link_class=FakeLink):
    vessels = {vessel.id: vessel for vessel in trajectories.initial_scene.vessels}
    links = {vessel_id: link_class(f"fake:{vessel_id}", vessel_id, GEOFENCE) for vessel_id in vessels}
    followers = {vessel_id: ReplayFollower(vessel, trajectories.state_list(vessel), trajectories.time_step) for vessel_id, vessel in vessels.items()}
    return links, followers, vessels


@pytest.fixture(autouse=True)
def isolated_fake_state():
    FakeLink.start_positions = {0: (0.0, 0.0), 1: (6000.0, 0.0)}
    FakeLink.connections = []
    yield
    FakeLink.start_positions = {}
    FakeLink.connections = []


@pytest.fixture
def straight():
    return straight_trajectories(timespan=60)


class TestRunMavlinkLockstep:
    def test_steps_are_recorded_for_every_vessel(self):
        trajectories = encounter_trajectories("head_on", 40)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 30, run_seed=3)
        assert result.vessel_ids == (0, 1)
        assert result.steps == 30
        assert len(result.states) == 31
        assert all(len(step) == 2 for step in result.states)

    def test_the_step_observer_sees_every_recorded_step_and_changes_nothing(self):
        trajectories = encounter_trajectories("head_on", 40)
        plain = run_mavlink_lockstep(*build_run(trajectories), 1.0, 12, run_seed=3)
        FakeLink.connections = []
        seen = []
        observed = run_mavlink_lockstep(*build_run(trajectories), 1.0, 12, run_seed=3, on_step=lambda index, samples: seen.append((index, dict(samples))))
        assert [index for index, _ in seen] == list(range(13))
        assert all(tuple(samples[vessel_id] for vessel_id in observed.vessel_ids) == step for (_, samples), step in zip(seen, observed.states))
        assert observed.state_digest() == plain.state_digest()

    def test_observations_are_stamped_on_the_step_boundaries(self):
        trajectories = encounter_trajectories("head_on", 40)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 20, run_seed=0)
        for step, observed in enumerate(result.states):
            for epoch, sample in zip(result.epoch_boot_ms, observed):
                assert sample.boot_ms - epoch == step * 1000

    def test_scenario_time_zero_is_on_a_multiple_of_the_start_quantum(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 5, run_seed=0)
        assert result.epoch_boot_ms[0] % int(START_QUANTUM_S * 1000) == 0
        assert result.epoch_boot_ms[0] >= 10_000 + 1000

    def test_explicit_start_time_is_used_for_the_first_vessel(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 5, run_seed=0, start_boot_s=100.0)
        assert result.epoch_boot_ms[0] == 100_000

    def test_a_start_time_too_close_to_arming_is_rejected(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        with pytest.raises(MavlinkLinkError, match="start_boot_s 1 is too early"):
            run_mavlink_lockstep(links, followers, vessels, 1.0, 5, run_seed=0, start_boot_s=1.0)

    def test_vessels_follow_their_references(self):
        trajectories = encounter_trajectories("head_on", 60)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 50, run_seed=0)
        own, target = vessels[0], vessels[1]
        for step in (10, 25, 50):
            reference_own = trajectories.state_list(own)[step]
            reference_target = trajectories.state_list(target)[step]
            observed_own, observed_target = (sample.state for sample in result.states[step])
            assert np.hypot(observed_own.x - reference_own.x, observed_own.y - reference_own.y) < 20.0
            assert np.hypot(observed_target.x - reference_target.x, observed_target.y - reference_target.y) < 20.0
        assert result.states[50][0].state.x > result.states[10][0].state.x
        assert result.states[50][1].state.x < result.states[10][1].state.x

    def test_every_vessel_is_switched_to_guided_by_its_first_command(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        run_mavlink_lockstep(links, followers, vessels, 1.0, 10, run_seed=0)
        for connection in FakeLink.connections:
            assert len(connection.mav.named("set_mode_send")) == 2, "HOLD while engaging, GUIDED with the first command"

    def test_one_command_is_sent_per_step_and_vessel(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        run_mavlink_lockstep(links, followers, vessels, 1.0, 10, run_seed=0)
        for connection in FakeLink.connections:
            assert len(connection.mav.named("set_position_target_local_ned_send")) == 10

    def test_command_time_is_the_step_boundary_of_that_vessel(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 5, run_seed=0)
        sent = FakeLink.connections[0].mav.named("set_position_target_local_ned_send")
        assert [args[0] for args in sent] == [result.epoch_boot_ms[0] + step * 1000 for step in range(5)]

    def test_participant_seeds_derive_from_the_run_seed(self):
        trajectories = encounter_trajectories("head_on", 10)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 3, run_seed=9)
        assert dict(result.participant_seeds) == {"replay/0": derive_seed(9, "replay/0"), "replay/1": derive_seed(9, "replay/1")}

    def test_repeats_against_the_same_fake_are_bit_identical(self):
        digests = []
        for _ in range(2):
            FakeLink.connections = []
            trajectories = encounter_trajectories("head_on", 40)
            links, followers, vessels = build_run(trajectories)
            digests.append(run_mavlink_lockstep(links, followers, vessels, 1.0, 30, run_seed=0).state_digest())
        assert digests[0] == digests[1]

    def test_digest_changes_with_the_states(self):
        trajectories = encounter_trajectories("head_on", 40)
        links, followers, vessels = build_run(trajectories)
        first = run_mavlink_lockstep(links, followers, vessels, 1.0, 20, run_seed=0)
        FakeLink.start_positions = {0: (50.0, 0.0), 1: (6000.0, 0.0)}
        links, followers, vessels = build_run(trajectories)
        second = run_mavlink_lockstep(links, followers, vessels, 1.0, 20, run_seed=0)
        assert first.state_digest() != second.state_digest()

    def test_all_streamed_samples_are_kept(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 5, run_seed=0)
        assert len(result.samples) == 2
        assert all(len(samples) > len(result.states) for samples in result.samples)

    def test_achieved_speedup_is_reported_from_the_wall_clock(self):
        trajectories = encounter_trajectories("head_on", 20)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 10, run_seed=0)
        assert result.wall_s >= 0
        assert result.achieved_speedup is None or result.achieved_speedup > 0


class TestPassiveVessels:
    def test_a_passive_vessel_is_observed_but_never_armed_or_commanded(self):
        trajectories = encounter_trajectories("head_on", 40)
        links, followers, vessels = build_run(trajectories)
        del followers[1]
        result = run_mavlink_lockstep(links, followers, vessels, 1.0, 10, run_seed=3, passive=frozenset({1}))
        own, operated = FakeLink.connections
        assert all(len(step) == 2 for step in result.states), "both vessels are recorded"
        assert own.armed and own.mav.named("set_position_target_local_ned_send")
        assert not operated.armed
        assert not operated.mav.named("set_mode_send") and not operated.mav.named("set_position_target_local_ned_send")
        assert [seed for seed, _ in result.participant_seeds] == ["replay/0"]

    def test_the_active_vessels_observe_the_passive_one(self):
        trajectories = encounter_trajectories("head_on", 40)
        links, followers, vessels = build_run(trajectories)
        del followers[1]
        seen = []

        class Watching(type(followers[0])):
            def on_step(self, request, observation):
                seen.append(set(observation.target_states))
                return super().on_step(request, observation)

        follower = followers[0]
        watching = Watching(follower.vessel, trajectories.state_list(follower.vessel), trajectories.time_step)
        run_mavlink_lockstep(links, {0: watching}, vessels, 1.0, 3, run_seed=3, passive=frozenset({1}))
        assert seen and all(targets == {1} for targets in seen)

    def test_a_passive_vessel_may_not_also_have_a_participant(self):
        links, followers, vessels = build_run(encounter_trajectories("head_on", 10))
        with pytest.raises(ValueError, match="must name the same vessels"):
            run_mavlink_lockstep(links, followers, vessels, 1.0, 3, run_seed=0, passive=frozenset({1}))


class TestValidation:
    def test_links_participants_and_vessels_must_name_the_same_vessels(self):
        trajectories = encounter_trajectories("head_on", 10)
        links, followers, vessels = build_run(trajectories)
        del followers[1]
        with pytest.raises(ValueError, match="must name the same vessels"):
            run_mavlink_lockstep(links, followers, vessels, 1.0, 3, run_seed=0)

    @pytest.mark.parametrize("dt", [0.0, 0.0005, 3.0, 5.0, 0.3333])
    def test_dt_must_be_whole_milliseconds_below_the_guided_timeout(self, dt):
        trajectories = encounter_trajectories("head_on", 10)
        links, followers, vessels = build_run(trajectories)
        with pytest.raises(ValueError):
            run_mavlink_lockstep(links, followers, vessels, dt, 3, run_seed=0)

    @pytest.mark.parametrize("time_step, dt", [(1, 1.0), (2, 2.0), (0.5, 0.5), (3, DEFAULT_LOCKSTEP_DT_S), (15, DEFAULT_LOCKSTEP_DT_S)])
    def test_a_run_without_dt_takes_the_trajectories_time_step_only_when_rover_can(self, time_step, dt):
        assert lockstep_dt(time_step) == dt

    def test_half_second_steps_run(self):
        trajectories = encounter_trajectories("head_on", 10)
        links, followers, vessels = build_run(trajectories)
        result = run_mavlink_lockstep(links, followers, vessels, 0.5, 6, run_seed=0)
        assert result.steps == 6

    def test_a_vessel_that_stays_in_hold_is_reported(self):
        steps = GUIDED_CHECK_MS // 1000 + 3
        trajectories = encounter_trajectories("head_on", steps + 5)
        links, followers, vessels = build_run(trajectories, StuckLink)
        with pytest.raises(MavlinkLinkError, match="did not switch from HOLD to GUIDED"):
            run_mavlink_lockstep(links, followers, vessels, 1.0, steps, run_seed=0)


class TestMavlinkReplayInstance:
    def test_every_vessel_replays_through_the_lockstep_adapter(self):
        instance = mavlink_replay_instance(encounter_trajectories("head_on", 10), SimulationLayerId.ARDUPILOT_SIM, speedup=4)
        assert set(instance.vessels) == {"0", "1"}
        assert instance.speedup == 4
        for vessel in instance.vessels.values():
            assert vessel.adapter_ids == ("replay_mavlink_lockstep",)
            assert str(vessel.stack) == "replay, ardupilot, ardupilot_sim"
        assert instance.vessels["0"].connection.agent_name == "vessel_0"


class TestMavlinkInstance:
    def test_usv_navigation_vessels_run_through_their_lockstep_adapter(self):
        instance = mavlink_instance(encounter_trajectories("head_on", 10), SimulationLayerId.GAZEBO, {0: AsvSoftwareId.USV_NAVIGATION})
        assert str(instance.vessels["0"].stack) == "usv_navigation, ardupilot, gazebo"
        assert instance.vessels["0"].adapter_ids == ("usv_navigation_mavlink_lockstep",)
        assert instance.vessels["1"].adapter_ids == ("replay_mavlink_lockstep",)

    def test_asv_software_without_a_lockstep_link_is_refused(self):
        with pytest.raises(ValueError, match="mission_planner has no lockstep MAVLink adapter"):
            mavlink_instance(encounter_trajectories("head_on", 10), SimulationLayerId.ARDUPILOT_SIM, {0: AsvSoftwareId.MISSION_PLANNER})


class TestRunMavlinkReplay:
    @pytest.fixture
    def resolver(self):
        registry = build_registry()
        registry.bind_runtime("replay_mavlink_lockstep", lambda: FakeLink)
        registry.bind_runtime("usv_navigation_mavlink_lockstep", lambda: FakeLink)
        return StackResolver(registry)

    def test_usv_navigation_steers_its_vessel_against_a_replaying_target(self, resolver):
        trajectories = encounter_trajectories("head_on", 30)
        instance = mavlink_instance(trajectories, SimulationLayerId.ARDUPILOT_SIM, {0: AsvSoftwareId.USV_NAVIGATION})
        result = run_mavlink_stack(trajectories, instance, GEOFENCE, resolver=resolver, steps=30)
        record = result.run_record
        assert set(record["participant_seeds"]) == {"usv_navigation/0", "replay/1"}
        assert {"usv_navigation_mavlink_lockstep", "replay_mavlink_lockstep"} <= set(record["specs"])
        assert record["usv_navigation"]["0"]["goal"] == [trajectories.state_list(trajectories.initial_scene.vessels[0])[-1].x, 0.0]
        assert result.states[-1][0].state.x > 100.0, "the own ship heads for its goal"

    def test_run_record_describes_the_chain_and_the_run(self, resolver, straight):
        FakeLink.start_positions = {0: (0.0, 0.0)}
        instance = mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM)
        result = run_mavlink_stack(straight, instance, GEOFENCE, resolver=resolver, steps=20)
        record = result.run_record
        assert record["stack"] == ["replay, ardupilot, ardupilot_sim"]
        assert record["repeatability_tier"] == "bounded"
        assert record["steps"] == 20
        assert record["dt"] == 1.0
        assert record["speedup"] == 1
        assert record["state_digest"] == result.state_digest()
        assert "replay_mavlink_lockstep" in record["specs"]
        assert record["environment"] == {"wind_vector": None, "waves": None, "seed": 0}
        assert set(record["participant_seeds"]) == {"replay/0"}

    def test_default_steps_cover_the_trajectory(self, resolver, straight):
        FakeLink.start_positions = {0: (0.0, 0.0)}
        result = run_mavlink_stack(straight, mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM), GEOFENCE, resolver=resolver)
        assert result.steps == 60

    def test_generated_trajectories_sampled_every_15_s_replay_at_one_second_steps(self, resolver, straight):
        FakeLink.start_positions = {0: (0.0, 0.0)}
        coarse = TrajectoryBuilder.default_trajectory_from_scene(straight.initial_scene, 15, 60)
        result = run_mavlink_stack(coarse, mavlink_replay_instance(coarse, SimulationLayerId.ARDUPILOT_SIM), GEOFENCE, resolver=resolver)
        assert result.dt == DEFAULT_LOCKSTEP_DT_S and result.steps == 60 and result.run_record["dt"] == DEFAULT_LOCKSTEP_DT_S
        assert result.states[-1][0].state.x == pytest.approx(straight.state_list(straight.initial_scene.vessels[0])[-1].x, abs=5.0)

    def test_links_are_closed_afterwards(self, resolver, straight):
        FakeLink.start_positions = {0: (0.0, 0.0)}
        run_mavlink_stack(straight, mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM), GEOFENCE, resolver=resolver, steps=5)
        assert all(connection.closed for connection in FakeLink.connections)

    def test_links_are_closed_when_the_run_fails(self, resolver, straight):
        FakeLink.start_positions = {0: (0.0, 0.0)}
        instance = mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM)
        with pytest.raises(MavlinkLinkError):
            run_mavlink_stack(straight, instance, GEOFENCE, resolver=resolver, steps=5, start_boot_s=1.0)
        assert FakeLink.connections and all(connection.closed for connection in FakeLink.connections)

    def test_endpoints_default_to_the_sitl_service_of_each_vessel(self, resolver, straight):
        endpoints_seen = []

        class Recording(FakeLink):
            def __init__(self, endpoint, vessel_id, reference_geofence, **kwargs):
                endpoints_seen.append(endpoint)
                super().__init__(endpoint, vessel_id, reference_geofence, **kwargs)

        resolver.registry.bind_runtime("replay_mavlink_lockstep", lambda: Recording)
        FakeLink.start_positions = {0: (0.0, 0.0)}
        run_mavlink_stack(straight, mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM), GEOFENCE, resolver=resolver, steps=3)
        assert endpoints_seen == ["tcp:vessel_0:5760"]
        endpoints_seen.clear()
        run_mavlink_stack(straight, mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM), GEOFENCE, resolver=resolver, steps=3, endpoints={"0": "tcp:localhost:5760"})
        assert endpoints_seen == ["tcp:localhost:5760"]

    def test_other_asv_adapters_are_rejected(self, resolver, straight):
        instance = mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM)
        for vessel in instance.vessels.values():
            vessel.adapter_ids = ("replay_arduagent_follower",)
        with pytest.raises(StackUnavailableError, match="run_mavlink_stack needs replay_mavlink_lockstep or usv_navigation_mavlink_lockstep for every simulated vessel"):
            run_mavlink_stack(straight, instance, GEOFENCE, resolver=resolver)

    def test_speedup_above_the_measured_limit_is_rejected(self, resolver, straight):
        instance = mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM, speedup=100)
        with pytest.raises(StackUnavailableError, match="exceeds the measured max_speedup 50"):
            run_mavlink_stack(straight, instance, GEOFENCE, resolver=resolver)

    def test_an_attended_run_leaves_mission_planner_vessels_to_the_operator(self, resolver):
        trajectories = encounter_trajectories("head_on", 30)
        instance = mavlink_instance(trajectories, SimulationLayerId.ARDUPILOT_SIM)
        operated = instance.vessels["1"]
        operated.stack = type(operated.stack)(AsvSoftwareId.MISSION_PLANNER, operated.stack.control_layer, operated.stack.simulation_layer)
        operated.adapter_ids = ()
        result = run_mavlink_stack(trajectories, instance, GEOFENCE, resolver=resolver, steps=5, attended=True)
        assert result.run_record["operator_vessels"] == [1]
        assert set(result.run_record["participant_seeds"]) == {"replay/0"}
        assert not FakeLink.connections[1].armed

    def test_the_run_is_validated_as_unattended(self, resolver, straight):
        from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId

        instance = mavlink_replay_instance(straight, SimulationLayerId.ARDUPILOT_SIM)
        for vessel in instance.vessels.values():
            vessel.stack = type(vessel.stack)(AsvSoftwareId.MISSION_PLANNER, vessel.stack.control_layer, vessel.stack.simulation_layer)
            vessel.adapter_ids = ()
        with pytest.raises(StackUnavailableError, match="interactive only"):
            run_mavlink_stack(straight, instance, GEOFENCE, resolver=resolver)
