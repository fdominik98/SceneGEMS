"""run_kinematic_replay and run_kinematic_closed_loop: results, run records and validation through the registry."""

import numpy as np
import pytest

from scenegems_tool.vessel_stack.contracts.clock import derive_seed
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import (
    KINEMATIC_REPLAY_STACK,
    KINEMATIC_USV_NAVIGATION_STACK,
    run_kinematic_closed_loop,
    run_kinematic_replay,
)
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories, straight_trajectories, wind_environment


@pytest.fixture(scope="module")
def head_on():
    return encounter_trajectories("head_on", 120)


class TestReplay:
    def test_replay_reproduces_the_generated_trajectory_exactly(self, head_on):
        result = run_kinematic_replay(head_on)
        assert result.steps == 120
        for step, scene in enumerate(head_on.scene_list):
            for index, actor in enumerate(result.actors):
                reference = scene[actor]
                state = result.states[step][index]
                assert (state.x, state.y, state.speed, state.heading) == (reference.x, reference.y, reference.speed, reference.heading)

    def test_digest_is_stable_across_repeats(self, head_on):
        assert run_kinematic_replay(head_on).state_digest() == run_kinematic_replay(head_on).state_digest()

    def test_digest_depends_on_the_scenario(self):
        first = run_kinematic_replay(encounter_trajectories("head_on", 60))
        second = run_kinematic_replay(encounter_trajectories("overtaking", 60))
        assert first.state_digest() != second.state_digest()

    def test_digest_depends_on_the_step_count(self, head_on):
        assert run_kinematic_replay(head_on, steps=50).state_digest() != run_kinematic_replay(head_on, steps=51).state_digest()

    def test_run_record_names_the_stack_specs_and_tier(self, head_on):
        record = run_kinematic_replay(head_on).run_record
        assert record["stack"] == str(KINEMATIC_REPLAY_STACK) == "replay, none, kinematic"
        assert record["specs"] == ["asv_system/replay", "replay_state_follower", "control_layer/none", "kinematic_command_input", "simulation_layer/kinematic"]
        assert record["repeatability_tier"] == "exact"
        assert record["dt"] == 1.0
        assert record["steps"] == 120
        assert record["environment"] == {"wind_vector": None, "waves": None, "seed": 0}

    def test_run_record_digest_matches_the_result(self, head_on):
        result = run_kinematic_replay(head_on)
        assert result.run_record["state_digest"] == result.state_digest()
        assert len(result.state_digest()) == 64

    def test_participant_seeds_derive_from_the_run_seed(self, head_on):
        from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig

        result = run_kinematic_replay(head_on, environment=EnvironmentConfig.calm(seed=7))
        assert result.run_seed == 7
        assert result.run_record["run_seed"] == 7
        assert result.run_record["participant_seeds"] == {"replay/0": derive_seed(7, "replay/0"), "replay/1": derive_seed(7, "replay/1")}

    def test_the_seed_changes_the_record_but_not_the_states_of_a_deterministic_follower(self, head_on):
        from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig

        first = run_kinematic_replay(head_on, environment=EnvironmentConfig.calm(seed=1))
        second = run_kinematic_replay(head_on, environment=EnvironmentConfig.calm(seed=2))
        assert first.run_record["participant_seeds"] != second.run_record["participant_seeds"]
        assert first.state_digest() == second.state_digest()

    def test_wind_is_rejected_through_the_registry_with_the_reason(self, head_on):
        with pytest.raises(StackUnavailableError, match="wind requested, but simulation_layer/kinematic does not support wind"):
            run_kinematic_replay(head_on, environment=wind_environment())

    def test_smaller_dt_gives_more_steps(self, head_on):
        result = run_kinematic_replay(head_on, dt=0.5, steps=20)
        assert result.steps == 20
        assert result.dt == 0.5
        assert result.run_record["dt"] == 0.5

    def test_finer_dt_stays_close_to_the_reference(self, head_on):
        result = run_kinematic_replay(head_on, dt=0.25, steps=240)
        own = [actor for actor in result.actors if actor.id == 0][0]
        index = result.actors.index(own)
        end = result.states[-1][index]
        reference = head_on.state_list(own)[60]
        assert np.hypot(end.x - reference.x, end.y - reference.y) < 0.1

    def test_non_integer_dt_cannot_become_trajectories(self, head_on):
        result = run_kinematic_replay(head_on, dt=0.5, steps=4)
        with pytest.raises(ValueError, match="integer time step"):
            result.to_trajectories()

    def test_trajectories_round_trip_at_integer_dt(self, head_on):
        result = run_kinematic_replay(head_on, steps=30)
        trajectories = result.to_trajectories()
        assert trajectories.time_step == 1
        assert len(trajectories) == 31
        own = trajectories.initial_scene.os
        reference_own = head_on.initial_scene.os
        assert trajectories.state_list(own)[30].x == pytest.approx(head_on.state_list(reference_own)[30].x)


class TestClosedLoop:
    def test_digest_is_stable_across_repeats(self):
        trajectories = encounter_trajectories("crossing_from_starboard", 600)
        assert run_kinematic_closed_loop(trajectories).state_digest() == run_kinematic_closed_loop(trajectories).state_digest()

    def test_run_record_has_the_per_vessel_stacks_and_the_usv_navigation_block(self):
        record = run_kinematic_closed_loop(encounter_trajectories("head_on", 60)).run_record
        assert record["stacks"] == {"0": str(KINEMATIC_USV_NAVIGATION_STACK), "1": str(KINEMATIC_REPLAY_STACK)}
        assert record["repeatability_tier"] == "exact"
        navigation = record["usv_navigation"]
        assert navigation["vessel"] == 0
        assert navigation["colav_automaton_commit"] == "54866f24a04987334057ae5c5896dfc3ee8ca058"
        assert navigation["parameters"]["goal"] == [pytest.approx(60 * 8.0), 0.0]
        assert navigation["parameters"]["v"] == 8.0
        assert navigation["parameters"]["Cs"] == 120.0
        assert "usv_navigation_in_process" in record["specs"]
        assert "replay_state_follower" in record["specs"]

    def test_target_vessel_replays_its_trajectory(self):
        trajectories = encounter_trajectories("head_on", 100)
        result = run_kinematic_closed_loop(trajectories)
        target = [actor for actor in result.actors if actor.id == 1][0]
        index = result.actors.index(target)
        for step, scene in enumerate(trajectories.scene_list):
            state = result.states[step][index]
            reference = scene[target]
            assert (state.x, state.y) == (reference.x, reference.y)

    def test_without_a_conflict_the_own_ship_follows_its_reference(self):
        trajectories = encounter_trajectories("head_on", 100)
        result = run_kinematic_closed_loop(trajectories)
        own = [actor for actor in result.actors if actor.id == 0][0]
        index = result.actors.index(own)
        end = result.states[-1][index]
        reference = trajectories.state_list(own)[100]
        assert np.hypot(end.x - reference.x, end.y - reference.y) < 1.0
        assert result.run_record["usv_navigation"]["transitions"] == []

    def test_unknown_own_ship_is_rejected(self):
        with pytest.raises(ValueError, match="No vessel with id 9 in the scene"):
            run_kinematic_closed_loop(encounter_trajectories("head_on", 10), own_ship_id=9)

    def test_another_vessel_can_be_the_navigating_one(self):
        record = run_kinematic_closed_loop(encounter_trajectories("head_on", 30), own_ship_id=1).run_record
        assert record["usv_navigation"]["vessel"] == 1
        assert record["stacks"] == {"0": str(KINEMATIC_REPLAY_STACK), "1": str(KINEMATIC_USV_NAVIGATION_STACK)}

    def test_wind_is_rejected_through_the_registry(self):
        with pytest.raises(StackUnavailableError, match="does not support wind"):
            run_kinematic_closed_loop(encounter_trajectories("head_on", 10), environment=wind_environment())

    def test_a_single_vessel_scene_runs(self):
        result = run_kinematic_closed_loop(straight_trajectories(timespan=30))
        assert result.steps == 30
        assert result.run_record["usv_navigation"]["transitions"] == []

    def test_explicit_steps_and_dt(self):
        result = run_kinematic_closed_loop(straight_trajectories(timespan=60), dt=2.0, steps=10)
        assert result.steps == 10
        assert result.dt == 2.0


class TestStepObserver:
    def test_the_observer_sees_every_recorded_state_and_changes_nothing(self, head_on):
        seen = []
        observed = run_kinematic_replay(head_on, on_step=lambda index, states: seen.append((index, states)) or False)
        plain = run_kinematic_replay(head_on)
        assert observed.state_digest() == plain.state_digest()
        assert [index for index, _ in seen] == list(range(121))
        assert [states for _, states in seen] == list(plain.states)

    def test_the_observer_ends_the_run_after_a_step(self, head_on):
        stopped = run_kinematic_replay(head_on, on_step=lambda index, states: index == 30)
        assert stopped.steps == 30 and stopped.run_record["steps"] == 30
        assert stopped.state_digest() == run_kinematic_replay(head_on, steps=30).state_digest()

    def test_the_observer_may_end_the_run_before_the_first_step(self, head_on):
        assert run_kinematic_replay(head_on, on_step=lambda index, states: True).steps == 0

    def test_the_closed_loop_takes_the_observer(self, head_on):
        indices = []
        result = run_kinematic_closed_loop(head_on, steps=20, on_step=lambda index, states: indices.append(index) or index == 10)
        assert result.steps == 10 and indices == list(range(11))
