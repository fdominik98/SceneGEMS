"""The MOOS-IvP component's server: the frame mapping, the files it writes for the helm, and the navigation step around the helm."""

import math
import subprocess
import sys
from typing import List, Sequence

import pytest

from scenegems_tool.vessel_stack.asv_system.asv_system_link import AsvSystemLink
from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest, asv_system_runtime
from scenegems_tool.vessel_stack.asv_system.moos_ivp import moos_ivp_server
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters, parameters_for
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server import (
    BASE_TIME,
    LEAD_IN_S,
    HelmPass,
    MoosIvpNavigator,
    Post,
    behaviour_text,
    compass_degrees,
    heading_radians,
    life_event,
    mission_text,
    node_report,
    speed_domain,
)
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SYSTEM, Endpoint, LineClient, LineServer, WireError
from scenegems_tool.vessel_stack.contracts.ports import VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from tests.scenegems_tool.vessel_stack.asv_system.moos_ivp.fake_helm import FakeHelm, FakeHelmSession, behaviour_value
from tests.scenegems_tool.vessel_stack.scenarios import SPEED, encounter_trajectories

VESSEL = {"id": 0, "length": 30.0, "max_speed": 20.0, "max_acceleration": 0.4, "max_angular_speed": 0.05}
CONFIG = {
    "dt": 1.0,
    "goal": [4000.0, 0.0],
    "speed": 8.0,
    "max_speed": 20.0,
    "avoidance": "colregs",
    "min_util_cpa_dist": 120.0,
    "max_util_cpa_dist": 240.0,
    "pwt_outer_dist": 1500.0,
    "pwt_inner_dist": 750.0,
    "completed_dist": 1650.0,
    "capture_radius": 60.0,
    "behaviour_options": [["pwt_grade", "linear"]],
    "contacts": {"1": {"length": 100.0}},
}


class ScriptedHelm:
    """A helm that answers every pass with the next of the passes it was given, and keeps what it was posted."""

    def __init__(self, passes: Sequence[HelmPass]):
        self._passes = list(passes)
        self.posted: List[List[Post]] = []
        self.times: List[float] = []
        self.started_with = None
        self.closed = False

    def start(self, mission, behaviours) -> None:
        self.started_with = (mission(9000), behaviours)

    def run_pass(self, moos_time, posts) -> HelmPass:
        self.times.append(moos_time)
        self.posted.append(list(posts))
        return self._passes.pop(0) if self._passes else HelmPass(heading=90.0, speed=8.0)

    def close(self) -> None:
        self.closed = True


def navigator(*passes: HelmPass, **overrides) -> MoosIvpNavigator:
    return MoosIvpNavigator(ScriptedHelm(passes), VESSEL, {**CONFIG, **overrides})


def names(posts: Sequence[Post]) -> List[str]:
    return [name for name, _ in posts]


class TestFrameMapping:
    @pytest.mark.parametrize("heading, compass", [(0.0, 90.0), (math.pi / 2, 0.0), (math.pi, 270.0), (-math.pi / 2, 180.0), (math.pi / 4, 45.0)])
    def test_a_heading_counterclockwise_from_east_is_a_compass_heading_clockwise_from_north(self, heading, compass):
        assert compass_degrees(heading) == pytest.approx(compass)
        back = heading_radians(compass)
        assert (math.cos(back), math.sin(back)) == pytest.approx((math.cos(heading), math.sin(heading))), "the same direction (west is pi or -pi)"

    @pytest.mark.parametrize("heading", [math.pi / 2 + 1e-17, math.pi / 2 - 1e-12, -math.pi, 7.0, -11.0])
    def test_a_compass_heading_is_within_a_full_turn(self, heading):
        assert 0.0 <= compass_degrees(heading) < 360.0

    @pytest.mark.parametrize("compass", [0.0, 123.0, 359.0, 360.0])
    def test_a_decided_heading_comes_back_within_half_a_turn(self, compass):
        assert -math.pi <= heading_radians(compass) <= math.pi

    def test_the_transit_speed_is_on_the_speed_grid(self):
        _, low, top, count = speed_domain(5.144, 12.0).split(":")
        step = (float(top) - float(low)) / (int(count) - 1)
        assert step * 20 == pytest.approx(5.144, abs=1e-12)
        assert float(top) <= 12.0 < float(top) + step, "the grid ends at the last step within the vessel's max speed"

    def test_a_contacts_report_is_in_fixed_notation(self):
        """The helm's ledger refuses a report with a number in exponent notation, and then forgets the contact."""
        report = node_report("c1", BASE_TIME + 3.0, (3.06e-16, 2500.0, 8.0, -math.pi / 2), 30.0)
        assert report == "NAME=c1,TYPE=ship,TIME=1000000003.000,X=0.0000,Y=2500.0000,SPD=8.0000,HDG=180.0000,LENGTH=30.00,MODE=DRIVE"

    def test_a_life_event_is_the_event_and_the_behaviour(self):
        assert life_event("iter=0,time=222.00, bname=avd_c1, btype=BHV_AvdColregsV22, event=spawn, seed=name=c1 # contact=c1,iter=222") == ("spawn", "avd_c1")


class TestHelmFiles:
    def test_the_mission_runs_one_stepped_helm(self):
        mission = mission_text(9003, 0.5, 8.0, 20.0)
        assert "ServerPort = 9003" in mission and "Community = own" in mission
        assert "AppTick = 4.0" in mission, "a period of half a step, so the helm is due at every step of the clock"
        for line in ("start_in_drive = true", "seed_random = false", "ok_skew = any", "domain = course:0:359:360", "behaviors = own.bhv"):
            assert line in mission
        assert "domain = speed:0:20.0:51" in mission

    @pytest.mark.parametrize("dt, app_tick", [(1.0, 2.0), (LEAD_IN_S, 1.0), (5.0, 1.0), (15.0, 1.0)])
    def test_the_helms_period_is_within_the_lead_in_and_the_step(self, dt, app_tick):
        """The helm's first pass is at BASE_TIME and the first step LEAD_IN_S later: with a period above that the helm is never due and the step times out."""
        mission = mission_text(9003, dt, 8.0, 20.0)
        assert f"AppTick = {app_tick!r}\n" in mission and f"CommsTick = {app_tick!r}\n" in mission
        assert 1.0 / app_tick <= min(dt, LEAD_IN_S), "the clock moves at least one period before every pass"

    def test_the_behaviour_file_is_the_transit_and_the_avoidance_template(self):
        behaviours = behaviour_text(CONFIG)
        assert behaviours.count("Behavior = ") == 2 and "Behavior = BHV_Waypoint" in behaviours and "Behavior = BHV_AvdColregsV22" in behaviours
        assert behaviour_value(behaviours, "point") == "4000.0000,0.0000"
        assert behaviour_value(behaviours, "endflag") == "SG_ARRIVED = true"
        assert float(behaviour_value(behaviours, "capture_radius")) == 60.0 and float(behaviour_value(behaviours, "slip_radius")) == 120.0
        for name in ("pwt_outer_dist", "pwt_inner_dist", "completed_dist", "min_util_cpa_dist", "max_util_cpa_dist"):
            assert float(behaviour_value(behaviours, name)) == CONFIG[name]
        assert behaviour_value(behaviours, "pwt_grade") == "linear", "a behaviour option is a line of the avoidance behaviour"
        for line in ("templating = spawn", "updates = CONTACT_INFO", "no_alert_request = true"):
            assert line in behaviours, "the navigator alerts the helm itself, in the place of a contact manager"

    def test_the_avoidance_behaviour_follows_the_parameter(self):
        assert "Behavior = BHV_AvoidCollision" in behaviour_text({**CONFIG, "avoidance": "cpa"})
        with pytest.raises(WireError, match="unknown avoidance 'evasive'"):
            behaviour_text({**CONFIG, "avoidance": "evasive"})


class TestNavigator:
    OWN = (10.0, -20.0, 7.5, 0.0)

    def test_a_step_posts_the_own_state_and_every_contact_at_the_steps_moos_time(self):
        subject = navigator()
        subject.start()
        subject.step(4.0, self.OWN, {2: (900.0, 0.0, 0.0, 0.0), 1: (3000.0, 50.0, 8.0, math.pi)})
        helm = subject.helm
        assert helm.times == [BASE_TIME + LEAD_IN_S + 4.0]
        (posts,) = helm.posted
        assert posts[:4] == [("NAV_X", 10.0), ("NAV_Y", -20.0), ("NAV_HEADING", 90.0), ("NAV_SPEED", 7.5)]
        assert posts[4] == ("NODE_REPORT", "NAME=c1,TYPE=ship,TIME=1000000006.000,X=3000.0000,Y=50.0000,SPD=8.0000,HDG=270.0000,LENGTH=100.00,MODE=DRIVE")
        assert posts[5][1].startswith("NAME=c2,") and "LENGTH=30.00" in posts[5][1], "contacts in actor order; one without a length of its own gets the own ship's"
        assert posts[6] == ("CONTACT_INFO", "name=c2 # contact=c2"), "only the contact within completed_dist gets its avoidance behaviour"

    def test_a_contact_is_alerted_once_while_it_stays_and_again_when_it_comes_back(self):
        subject = navigator()
        ranges = [2000.0, 1600.0, 1000.0, 1700.0, 1814.0, 1816.0, 1700.0, 1600.0]
        for index, distance in enumerate(ranges):
            subject.step(float(index), (0.0, 0.0, 8.0, 0.0), {1: (distance, 0.0, 8.0, math.pi)})
        alerted = [index for index, posts in enumerate(subject.helm.posted) if "CONTACT_INFO" in names(posts)]
        assert alerted == [1, 7], "within completed_dist (1650 m) at step 1; released at 1.1 times it (1815 m) at step 5, where the helm's behaviour ends; back in at step 7"

    def test_the_decision_is_the_command_in_the_scenegems_frame(self):
        subject = navigator(HelmPass(heading=0.0, speed=6.4), HelmPass(heading=135.0, speed=8.0))
        assert subject.step(0.0, self.OWN, {}) == (pytest.approx(math.pi / 2), 6.4)
        assert subject.step(1.0, self.OWN, {}) == (pytest.approx(-math.pi / 4), 8.0)
        assert subject.no_decision_steps == 0

    def test_a_step_without_a_decision_holds_the_heading_and_the_last_decided_speed(self):
        subject = navigator(HelmPass(heading=90.0, speed=6.0), HelmPass(), HelmPass(heading=10.0, speed=8.0, allstop="BehaviorError"), HelmPass(heading=90.0, speed=7.0))
        subject.step(0.0, self.OWN, {})
        assert subject.step(1.0, (0.0, 0.0, 5.0, 0.3), {}) == (0.3, 6.0)
        assert subject.step(2.0, (0.0, 0.0, 5.0, 0.4), {}) == (0.4, 6.0), "an all-stop that is not clear is no decision either"
        assert subject.step(3.0, self.OWN, {})[1] == 7.0
        assert subject.no_decision_steps == 2
        assert subject.allstops == [[2.0, "BehaviorError"], [3.0, "clear"]]

    def test_after_the_goal_the_navigator_holds_course_and_asks_the_helm_no_more(self):
        subject = navigator(HelmPass(heading=90.0, speed=8.0), HelmPass(arrived=True, allstop="NothingToDo"))
        subject.step(0.0, self.OWN, {})
        assert subject.step(1.0, (3990.0, 0.0, 8.0, 0.1), {}) == (0.1, 8.0)
        assert subject.step(2.0, (3998.0, 0.0, 8.0, 0.2), {}) == (0.2, 8.0)
        assert subject.goal_reached_at == 1.0 and len(subject.helm.posted) == 2
        assert subject.no_decision_steps == 0, "arriving is not a missing decision"

    def test_the_report_is_what_the_run_record_keeps(self, monkeypatch):
        monkeypatch.setenv("MOOS_IVP_COMMIT", "0123abc")
        spawn = "iter=0,time=5.00, bname=avd_c1, btype=BHV_AvdColregsV22, event=spawn, seed=name=c1 # contact=c1,iter=5"
        subject = navigator(HelmPass(heading=90.0, speed=8.0, life_events=[spawn], warnings=["transit: slow"]), HelmPass(heading=91.0, speed=8.0, warnings=["transit: slow"]))
        subject.step(0.0, self.OWN, {})
        subject.step(1.0, self.OWN, {})
        assert subject.report() == {
            "moos_ivp_commit": "0123abc",
            "avoidance_behaviour": "BHV_AvdColregsV22",
            "events": [[0.0, "spawn", "avd_c1"]],
            "allstops": [],
            "goal_reached_at": None,
            "no_decision_steps": 0,
            "warnings": ["transit: slow"],
        }

    def test_closing_the_navigator_ends_the_helm(self):
        subject = navigator()
        subject.close()
        assert subject.helm.closed


def moos_ivp_request(trajectories) -> ParticipantRequest:
    vessel = trajectories.initial_scene.os
    stack = VesselStackConfig(asv_system=AsvSystemId.MOOS_IVP, control_layer=ControlLayerId.NONE, simulation_layer=SimulationLayerId.KINEMATIC)
    return ParticipantRequest(vessel, "os", AsvSystemId.MOOS_IVP, default_resolver().resolve(stack).asv_adapter, trajectories, 1.0, parameters_for(vessel, trajectories, 1.0))


class TestBehindTheWireProtocol:
    @pytest.fixture
    def head_on(self):
        return encounter_trajectories("head_on", 400)

    def test_the_container_answers_a_runners_link(self, head_on):
        FakeHelm.started.clear()
        request = moos_ivp_request(head_on)
        with LineServer(ROLE_ASV_SYSTEM, "moos_ivp", FakeHelmSession, host="127.0.0.1") as server:
            link = AsvSystemLink(Endpoint("127.0.0.1", server.port), request).connect(5.0)
            link.start(7)
            assert link.participant_id == "moos_ivp/0" and link.mission is None
            (helm,) = FakeHelm.started
            assert behaviour_value(helm.behaviours, "point") == f"{400 * SPEED:.4f},0.0000", "the goal is the end of the own ship's trajectory"
            own, target = head_on.initial_scene.vessels
            own_state = head_on.initial_scene[own]
            for index in range(3):
                step = StepRequest(index, float(index), float(index + 1))
                command = link.on_step(step, VesselStateObservation(float(index), own, own_state, {target.id: head_on.state_list(target)[index]}))
                assert command.speed == SPEED
                assert command.heading == pytest.approx(math.radians(-30.0)), "the target is within the outer distance from the start, so the fake helm turns to starboard"
                own_state = own.simulate(own_state, (command.heading, command.speed), 1.0)
            report = link.report()
            assert report["events"] == [[0.0, "spawn", "avd_c1"]] and report["goal_reached_at"] is None and report["no_decision_steps"] == 0
            assert not helm.closed
            link.close()
            # The server takes one runner at a time, so the next one is answered only once the first one's session has ended.
            LineClient(Endpoint("127.0.0.1", server.port), ROLE_ASV_SYSTEM).connect(5.0)
            assert helm.closed, "the session ends its helm when the runner's connection ends"

    def test_a_new_start_on_the_same_connection_ends_the_helm_before(self, head_on):
        FakeHelm.started.clear()
        session = FakeHelmSession()
        start = {"op": "start", "seed": 0, "vessel": VESSEL, "config": CONFIG}
        session.handle(start)
        session.handle(start)
        first, second = FakeHelm.started
        assert first.closed and not second.closed
        session.close()
        assert second.closed

    def test_a_step_before_start_is_an_error(self):
        with pytest.raises(WireError, match="step before start"):
            FakeHelmSession().handle({"op": "step", "index": 0, "time": 0.0, "target_time": 1.0, "own": [0, 0, 0, 0], "targets": {}})

    def test_the_server_needs_nothing_of_scenegems_but_the_wire_protocol(self):
        """The MOOS-IvP image holds this file and lockstep_wire.py, and no Python package beyond the standard library."""
        code = (
            "import sys; before = set(sys.modules); sys.path.insert(0, sys.argv[1]);"
            "import scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server;"
            "print(sorted(name for name in set(sys.modules) - before if name.split('.')[0] in ('scenegems_tool', 'concrete_level', 'utils', 'numpy', 'scipy', 'yaml', 'pydantic')))"
        )
        source_root = moos_ivp_server.__file__.split("scenegems_tool")[0]
        modules = eval(subprocess.run([sys.executable, "-I", "-c", code, source_root], capture_output=True, text=True, check=True).stdout)
        packages = {
            "scenegems_tool",
            "scenegems_tool.vessel_stack",
            "scenegems_tool.vessel_stack.contracts",
            "scenegems_tool.vessel_stack.asv_system",
            "scenegems_tool.vessel_stack.asv_system.moos_ivp",
        }
        assert set(modules) - packages == {"scenegems_tool.vessel_stack.contracts.lockstep_wire", "scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server"}


class TestRuntime:
    def test_the_start_config_is_the_parameters_the_step_and_the_contacts_lengths(self):
        trajectories = encounter_trajectories("head_on", 100)
        request = moos_ivp_request(trajectories)
        config = asv_system_runtime(AsvSystemId.MOOS_IVP).start_config(request)
        assert config == {"dt": 1.0, **request.parameters.as_dict(), "contacts": {"1": {"length": 30.0}}}
        assert isinstance(request.parameters, MoosIvpParameters)

    def test_the_parameters_are_required(self):
        trajectories = encounter_trajectories("head_on", 100)
        request = moos_ivp_request(trajectories)
        without = ParticipantRequest(request.vessel, "os", AsvSystemId.MOOS_IVP, request.adapter, trajectories, 1.0)
        with pytest.raises(ValueError, match="needs MoosIvpParameters"):
            asv_system_runtime(AsvSystemId.MOOS_IVP).start_config(without)

    def test_the_helm_has_no_participant_in_the_callers_process(self):
        trajectories = encounter_trajectories("head_on", 100)
        with pytest.raises(RuntimeError, match="MOOS-IvP runs only in its container"):
            asv_system_runtime(AsvSystemId.MOOS_IVP).in_process(moos_ivp_request(trajectories))


class TestMoosdbPorts:
    """Every vessel's MOOSDB has a port of its own (the stack's generator gives --moosdb-port), and a run takes the next one of the vessel's window."""

    @pytest.fixture(autouse=True)
    def helm_ports(self, monkeypatch):
        monkeypatch.setattr(moos_ivp_server.HelmProcesses, "first_port", moos_ivp_server.DEFAULT_MOOSDB_PORT)
        monkeypatch.setattr(moos_ivp_server.HelmProcesses, "_runs", 0)

    def test_runs_take_consecutive_ports_from_the_first_and_come_round_after_a_window(self):
        moos_ivp_server.HelmProcesses.first_port = 12432
        ports = [moos_ivp_server.HelmProcesses.take_port() for _ in range(moos_ivp_server.MOOSDB_PORTS_PER_VESSEL + 2)]
        assert ports[:3] == [12432, 12433, 12434] and ports[-3:] == [12447, 12432, 12433]
        assert max(ports) < 12432 + moos_ivp_server.MOOSDB_PORTS_PER_VESSEL, "never into the next vessel's window"

    def test_the_servers_arguments_set_the_moosdb_port_and_leave_the_rest_to_the_wire_protocol(self, monkeypatch):
        served = {}
        monkeypatch.setattr(moos_ivp_server, "serve_component", lambda role, implementation, factory, argv, *, default_port: served.update(argv=argv, default_port=default_port))
        moos_ivp_server.main(["--port", "12002", "--moosdb-port", "12432"])
        assert served == {"argv": ["--port", "12002"], "default_port": moos_ivp_server.DEFAULT_PORT}
        assert moos_ivp_server.HelmProcesses.first_port == 12432

    def test_without_the_argument_the_moosdb_port_is_vessel_0_s(self, monkeypatch):
        monkeypatch.setattr(moos_ivp_server, "serve_component", lambda *args, **kwargs: None)
        moos_ivp_server.main(["--port", "12000"])
        assert moos_ivp_server.HelmProcesses.first_port == moos_ivp_server.DEFAULT_MOOSDB_PORT


class TestLogTail:
    """What an error carries of a process's log: its last whole lines on one line, readable where the console shows the reason of a failed case."""

    def test_the_colour_codes_of_a_terminal_are_left_out(self):
        log = "\x1b[32mLoading behavior dynamic libraries specified in IVP_BEHAVIOR_DIRS...\n\x1b[0m  Environment variable IVP_BEHAVIOR_DIRS not set.\n\x1b[1;31mpHelmIvP is Running:\x1b[0m\n"
        assert moos_ivp_server.log_tail(log) == "Loading behavior dynamic libraries specified in IVP_BEHAVIOR_DIRS... | Environment variable IVP_BEHAVIOR_DIRS not set. | pHelmIvP is Running:"

    def test_a_long_log_gives_its_last_whole_lines(self):
        log = "".join(f"line {index:03d} of the helm\n" for index in range(200))
        tail = moos_ivp_server.log_tail(log, characters=70)
        assert tail == "line 197 of the helm | line 198 of the helm | line 199 of the helm", "the line the cut went through is left out"
        assert len(moos_ivp_server.log_tail(log)) <= moos_ivp_server.LOG_TAIL_CHARACTERS + 3 * 75

    def test_a_short_log_is_given_whole_and_blank_lines_are_skipped(self):
        assert moos_ivp_server.log_tail("first\n\n   \nsecond\n") == "first | second"
        assert moos_ivp_server.log_tail("") == ""
        assert moos_ivp_server.log_tail("one line without an end", characters=8) == "t an end", "a log of one long line keeps its end"

    def test_an_error_names_its_cause_first_and_then_whose_log_follows(self, tmp_path):
        helm = moos_ivp_server.HelmProcesses.__new__(moos_ivp_server.HelmProcesses)
        helm._folder = str(tmp_path)
        (tmp_path / "pHelmIvP.log").write_text("\x1b[32mpHelmIvP is Running:\x1b[0m\n|-Baseline AppTick   @ 0.4 Hz\n", encoding="utf-8")
        assert helm._log_tail("pHelmIvP") == "The end of pHelmIvP's log: pHelmIvP is Running: | |-Baseline AppTick   @ 0.4 Hz"
