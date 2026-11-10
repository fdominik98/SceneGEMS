"""KinematicSimulation and run_lockstep: the lockstep contract of the kinematic layer."""

import pytest

from scenegems_tool.vessel_stack.asv_system.replay.replay_follower import ReplayFollower
from scenegems_tool.vessel_stack.contracts.clock import LockstepViolation, StepAck
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_lockstep
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene, encounter_trajectories


@pytest.fixture
def simulation() -> KinematicSimulation:
    return KinematicSimulation(encounter_scene("head_on"), 1.0, ["a", "b"])


def acks(simulation: KinematicSimulation, *participants: str):
    index = simulation.step_request().index
    return [StepAck(participant, index) for participant in participants]


def test_initial_snapshot_is_the_scene(simulation):
    states = simulation.snapshot()
    assert [state.x for state in states] == [0.0, 6000.0]
    assert simulation.time == 0.0


def test_actors_keep_the_scene_order(simulation):
    assert [actor.id for actor in simulation.actors] == [0, 1]


def test_uncommanded_vessels_hold_heading_and_speed(simulation):
    simulation.step({}, acks(simulation, "a", "b"))
    own, target = simulation.snapshot()
    assert (own.x, own.y, own.speed, own.heading) == pytest.approx((8.0, 0.0, 8.0, 0.0))
    assert target.x == pytest.approx(5992.0)
    assert simulation.time == 1.0


def test_command_is_limited_by_the_vessel_turn_rate(simulation):
    simulation.step({0: HeadingSpeedCommand(heading=3.0, speed=8.0)}, acks(simulation, "a", "b"))
    own = simulation.snapshot()[0]
    assert own.heading == pytest.approx(0.05)


def test_observation_has_own_state_and_all_other_actors(simulation):
    observation = simulation.observe(0)
    assert observation.sim_time == 0.0
    assert observation.vessel.id == 0
    assert observation.own_state.x == 0.0
    assert set(observation.target_states) == {1}


def test_step_request_follows_the_clock(simulation):
    simulation.step({}, acks(simulation, "a", "b"))
    request = simulation.step_request()
    assert (request.index, request.time, request.target_time) == (1, 1.0, 2.0)


def test_missing_acknowledgement_blocks_the_step(simulation):
    with pytest.raises(LockstepViolation, match="missing acknowledgements from b"):
        simulation.step({}, acks(simulation, "a"))
    assert simulation.time == 0.0


def test_stale_acknowledgement_is_rejected(simulation):
    with pytest.raises(LockstepViolation, match="acknowledged step 5"):
        simulation.step({}, [StepAck("a", 5), StepAck("b", 5)])


def test_commands_for_unknown_vessels_are_rejected(simulation):
    with pytest.raises(ValueError, match=r"not in the scene: \[7\]"):
        simulation.step({7: HeadingSpeedCommand(0.0, 1.0)}, acks(simulation, "a", "b"))


def test_run_lockstep_requires_the_clock_participants():
    trajectories = encounter_trajectories("head_on", 10)
    vessels = trajectories.initial_scene.vessels
    followers = {vessel.id: ReplayFollower(vessel, trajectories.state_list(vessel), 1) for vessel in vessels}
    simulation = KinematicSimulation(trajectories.initial_scene, 1.0, ["replay/0"])
    with pytest.raises(ValueError, match="do not match the clock participants"):
        run_lockstep(simulation, followers, 5, 0)


def test_run_lockstep_starts_every_participant_with_a_derived_seed():
    trajectories = encounter_trajectories("head_on", 10)
    vessels = trajectories.initial_scene.vessels
    started = {}

    class Recording(ReplayFollower):
        def start(self, seed):
            started[self.participant_id] = seed

    followers = {vessel.id: Recording(vessel, trajectories.state_list(vessel), 1) for vessel in vessels}
    simulation = KinematicSimulation(trajectories.initial_scene, 1.0, [follower.participant_id for follower in followers.values()])
    result = run_lockstep(simulation, followers, 3, 11)
    assert set(started) == {"replay/0", "replay/1"}
    assert dict(result.participant_seeds) == started
    assert len(result.states) == 4
