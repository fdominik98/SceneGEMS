"""The kinematic stack with every layer behind the wire protocol: the same run as in process, bit for bit."""

import pytest

from scenegems_tool.vessel_stack.contracts.clock import LockstepViolation, StepAck
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_SIMULATOR, Endpoint, LineClient, LineServer, WireError
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId
from scenegems_tool.vessel_stack.contracts.stack_services import KINEMATIC_SIM_SERVICE
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import kinematic_instance, run_kinematic_closed_loop, run_kinematic_instance, run_kinematic_replay
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_link import KinematicSimLink
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server import KinematicSimSession
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_endpoints, loopback_hosting
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories


@pytest.fixture(scope="module")
def head_on():
    return encounter_trajectories("head_on", 120)


@pytest.fixture
def simulator():
    with LineServer(ROLE_SIMULATOR, "kinematic", KinematicSimSession, host="127.0.0.1") as server:
        yield Endpoint("127.0.0.1", server.port)


class TestKinematicSimLink:
    def test_it_steps_as_the_simulation_in_process_does(self, simulator, head_on):
        scene = head_on.initial_scene
        local = KinematicSimulation(scene, 1.0, ["a"])
        link = KinematicSimLink(simulator, scene, 1.0, ["a"]).connect(5.0)
        assert link.actors == local.actors and link.snapshot() == local.snapshot()
        for step in range(5):
            commands = {0: HeadingSpeedCommand(heading=0.1 * step, speed=3.0 + step)}  # vessel 1 is not commanded and holds its course
            acks = [StepAck("a", step)]
            local.step(commands, acks)
            link.step(commands, acks)
            assert link.snapshot() == local.snapshot()
            assert link.time == local.time and link.step_request() == local.step_request()
            assert link.observe(0).own_state == local.observe(0).own_state and link.observe(0).target_states == local.observe(0).target_states
        link.close()

    def test_the_clock_stays_with_the_runner(self, simulator, head_on):
        link = KinematicSimLink(simulator, head_on.initial_scene, 1.0, ["a", "b"]).connect(5.0)
        with pytest.raises(LockstepViolation, match="missing acknowledgements from b"):
            link.step({}, [StepAck("a", 0)])
        link.close()

    def test_a_command_for_an_unknown_vessel_is_refused_before_it_is_sent(self, simulator, head_on):
        link = KinematicSimLink(simulator, head_on.initial_scene, 1.0, []).connect(5.0)
        with pytest.raises(ValueError, match=r"not in the scene: \[9\]"):
            link.step({9: HeadingSpeedCommand(0.0, 1.0)}, [])
        link.close()

    def test_a_step_before_start_is_an_error(self, simulator):
        client = LineClient(simulator, ROLE_SIMULATOR)
        client.connect(5.0)
        with pytest.raises(WireError, match="step before start"):
            client.request({"op": "step", "commands": {}})


class TestRunsInContainers:
    def test_a_replay_is_the_in_process_replay_bit_for_bit(self, head_on):
        in_process = run_kinematic_replay(head_on)
        with loopback_hosting(kinematic_instance(head_on)) as hosting:
            contained = run_kinematic_replay(head_on, hosting=hosting)
        assert contained.state_digest() == in_process.state_digest()
        assert contained.run_record == in_process.run_record
        assert contained.steps == 120

    def test_the_replay_still_reproduces_the_generated_trajectory_exactly(self, head_on):
        with loopback_hosting(kinematic_instance(head_on)) as hosting:
            result = run_kinematic_replay(head_on, hosting=hosting)
        for step, scene in enumerate(head_on.scene_list):
            for index, actor in enumerate(result.actors):
                reference, state = scene[actor], result.states[step][index]
                assert (state.x, state.y, state.speed, state.heading) == (reference.x, reference.y, reference.speed, reference.heading)

    @pytest.mark.parametrize("encounter", ["head_on", "crossing_from_starboard", "overtaking"])
    def test_usv_navigation_gives_the_in_process_run_bit_for_bit(self, encounter):
        trajectories = encounter_trajectories(encounter, 900)
        in_process = run_kinematic_closed_loop(trajectories)
        with loopback_hosting(kinematic_instance(trajectories, {0: AsvSystemId.USV_NAVIGATION})) as hosting:
            contained = run_kinematic_closed_loop(trajectories, hosting=hosting)
        assert contained.state_digest() == in_process.state_digest()
        assert contained.run_record == in_process.run_record, "the transitions and the arrival travel in the software's report"
        assert contained.run_record["usv_navigation"]["transitions"], "the encounter makes the automaton leave its first mode"

    def test_an_early_stop_ends_the_run_and_releases_the_containers(self, head_on):
        instance = kinematic_instance(head_on)
        with loopback_endpoints(instance) as endpoints:
            from scenegems_tool.vessel_stack.hosting import ContainerHosting

            first = run_kinematic_instance(head_on, instance, hosting=ContainerHosting(endpoints, connect_timeout_s=5.0), on_step=lambda index, states: index == 10)
            assert first.result.steps == 10
            # Each component serves one runner at a time: a second run connects only because the first one closed its links.
            second = run_kinematic_instance(head_on, instance, hosting=ContainerHosting(endpoints, connect_timeout_s=5.0), steps=10)
        assert second.result.state_digest() == first.result.state_digest()

    def test_a_missing_container_fails_the_run_with_its_address(self, head_on):
        instance = kinematic_instance(head_on)
        with loopback_endpoints(instance) as endpoints:
            from scenegems_tool.vessel_stack.hosting import ContainerHosting

            with LineServer(ROLE_SIMULATOR, "kinematic", KinematicSimSession, host="127.0.0.1") as gone:
                unreachable = Endpoint("127.0.0.1", gone.port)
            hosting = ContainerHosting({**endpoints, KINEMATIC_SIM_SERVICE: unreachable}, connect_timeout_s=0.3)
            with pytest.raises(WireError, match=f"no simulator at 127.0.0.1:{unreachable.port}"):
                run_kinematic_instance(head_on, instance, hosting=hosting)
