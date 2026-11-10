"""LiveRunRecorder: live runs of the workbench recorded as workbench entries (design doc 6.4).

The first classes run the recorder on fake campaign stores and a fake engine with a real artifact
store on in-memory records; the last one runs it on Postgres with the real pipeline engine, whose
post-hoc monitor job (the fake executor) judges the recorded run.
"""

import asyncio
import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List

import numpy as np
import pytest

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.assurance.campaign.domain_presets import default_domain
from scenegems_tool.assurance.pipeline.case_machine import RecordedRun
from scenegems_tool.gateway.live_run_recorder import (
    INPUT_ROLE,
    NO_STATE_MESSAGE,
    UNAVAILABLE_MESSAGE,
    LiveRunRecorder,
    LiveRunSetup,
    LiveSessionRecording,
    environment_settings,
)
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.schema import ArtifactHolderKind, CampaignActualState, CampaignDesiredState, CampaignKind, CampaignOrigin
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, EnvironmentConfig, VesselStackConfig, WaveConfig
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories, stack_instance

NOW = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)


class FakeCampaigns:
    def __init__(self):
        self.created: List[SimpleNamespace] = []
        self.desired = {}

    def create_campaign(self, name, config, config_hash, classes, pinned_fingerprints=None, desired_state=CampaignDesiredState.PAUSED, *, kind, origin, session=None):
        campaign = SimpleNamespace(campaign_id=f"entry-{len(self.created) + 1}", name=name, config=config, classes=classes, desired_state=desired_state, kind=kind, origin=origin)
        self.created.append(campaign)
        return campaign

    def set_desired_state(self, campaign_id, state, expected=None, *, session=None):
        self.desired[campaign_id] = state


CLUSTER_DOMAIN = {"colregs_constants": "SAFE_DISTANCE: 400\n", "vessel_types": "Ferry: {}\n", "obstacle_types": "Buoy: {}\n"}


class FakeDomain:
    """The cluster's domain configuration: none saved, unless a test saves one."""

    def __init__(self):
        self.saved = None

    def current(self, *, session=None):
        return self.saved


class FakeEngine:
    def __init__(self, error: Exception = None):
        self.error = error
        self.runs: List[tuple] = []
        self.wakes = 0

    def wake(self):
        self.wakes += 1

    async def record_external_run(self, campaign_id, run, class_id=None):
        if self.error is not None:
            raise self.error
        self.runs.append((campaign_id, run, class_id))
        return RecordedRun(campaign_id, 7, 70, f"campaign:{campaign_id}:case:7:monitor:0")


def live_setup(config=None, length: int = 20) -> LiveRunSetup:
    config = config or stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"], speedup=2)
    return LiveRunSetup(scenario_name="head_on.json", trajectories=encounter_trajectories("head_on", length), simulation_config=config, time_step=1)


@pytest.fixture
def world(tmp_path):
    records = InMemoryArtifactRecords(lambda: NOW)
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records)
    campaigns, engine, announced = FakeCampaigns(), FakeEngine(), []
    domain = FakeDomain()
    recorder = LiveRunRecorder(SimpleNamespace(campaigns=campaigns, domain=domain), artifacts, engine, announce=announced.extend, seeds=lambda: 1234, clock=lambda: NOW)
    return SimpleNamespace(records=records, artifacts=artifacts, campaigns=campaigns, domain=domain, engine=engine, recorder=recorder, announced=announced)


async def recording(world, setup=None, recorder=...):
    sent: List[dict] = []
    session = LiveSessionRecording(world.recorder if recorder is ... else recorder, setup or live_setup(), asyncio.get_running_loop(), sent.append)
    return session, sent


async def finished(session: LiveSessionRecording):
    """Waits for every recording of the session, then for their reports."""
    for run in session.recordings:
        await asyncio.wrap_future(run.future)
    await settle()


def statuses(sent):
    return [(message["status"], message["campaignId"], message["caseId"]) for message in sent]


def stored_trajectories(world, reference) -> Trajectories:
    return Trajectories.from_dict(json.loads(world.artifacts.store.read(reference["sha256"])))


@pytest.mark.anyio
class TestRecordedRuns:
    async def test_a_completed_run_becomes_a_workbench_entry_with_its_recorded_run(self, world):
        setup = live_setup()
        session, sent = await recording(world, setup)
        session.run_started()
        for second, scene in enumerate(setup.trajectories.scene_list[:6]):
            session.state_simulated(float(second), scene)
        session.run_ended()
        await finished(session)
        assert statuses(sent) == [("recording", None, None), ("recording", "entry-1", None), ("saved", "entry-1", 7)]
        assert sent[-1]["type"] == "run_recording" and sent[-1]["message"] == "6 states (completed); the post-hoc monitor judges it"
        ((campaign_id, run, class_id),) = world.engine.runs
        assert (campaign_id, class_id) == ("entry-1", "item/0")
        assert (run.dt, run.steps, run.repeatability_tier, run.state_digest, run.worker_node_id) == (1.0, 5, "bounded", None, None)
        assert run.state_log["kind"] == "trajectories" and run.state_log["pointer"] is None
        log = stored_trajectories(world, run.state_log)
        assert (len(log), log.time_step) == (6, 1) and log.scene_list[5].to_dict() == setup.trajectories.scene_list[5].to_dict()
        assert run.stack["simulation_layer"] == "ardupilot_sim" and run.stack["speedup"] == 2
        assert run.stack["vessels"]["1"] == {
            "context": "simulation",
            "asv_system": "replay",
            "control_layer": "ardupilot",
            "simulation_layer": "ardupilot_sim",
            "adapter_ids": ["replay_arduagent_follower"],
            "agent_name": "agent_1",
        }
        assert run.environment == {"wind_vector": [0.0, 0.0, 0.0], "waves": None} and set(run.durations_s) == {"running_s"}
        assert world.campaigns.desired == {}

    async def test_the_entry_is_a_started_live_session_entry_whose_input_item_is_the_loaded_trajectories(self, world):
        setup = live_setup()
        session, _ = await recording(world, setup)
        session.run_started()
        session.state_simulated(0.0, setup.trajectories.initial_scene)
        session.run_ended()
        await finished(session)
        (campaign,) = world.campaigns.created
        assert (campaign.kind, campaign.origin, campaign.desired_state) == (CampaignKind.WORKBENCH, CampaignOrigin.LIVE_SESSION, CampaignDesiredState.RUNNING)
        assert campaign.name == "Live session: head_on.json (2026-10-28 09:30)"
        config = campaign.config
        assert (config["format"], config["steps"]) == (2, ["simulation"])
        (item,) = config["input"]["items"]
        assert item["source"]["file"] == "head_on.json"
        assert (item["ref"]["kind"], item["ref"]["pointer"]) == ("trajectories", None)
        assert stored_trajectories(world, item["ref"]).to_dict() == setup.trajectories.to_dict()
        (run,) = config["execution"]["runs"]
        assert (run["monitor"], run["repeats"]) == ("post_hoc", 1)
        assert config["policy"]["keep_frames"] is True and config["policy"]["seed"] == 1234
        (spec,) = campaign.classes
        assert (spec.class_id, spec.content_hash, spec.vessel_count, spec.quota) == ("item/0", item["ref"]["sha256"], 2, 1)
        assert (item["ref"]["sha256"], "campaign", "entry-1", INPUT_ROLE) in world.records.references
        assert world.announced == ["entry-1"] and world.engine.wakes == 1
        assert world.engine.runs[0][1].trajectories_complete is True
        assert config["domain"]["colregs_constants"] == default_domain()["colregs_constants"]  # no cluster domain saved: the default presets

    async def test_the_entry_judges_its_run_with_the_clusters_domain_configuration(self, world):
        world.domain.saved = SimpleNamespace(contents=lambda: CLUSTER_DOMAIN)
        setup = live_setup()
        session, _ = await recording(world, setup)
        session.run_started()
        session.state_simulated(0.0, setup.trajectories.initial_scene)
        session.run_ended()
        await finished(session)
        (campaign,) = world.campaigns.created
        assert {key: campaign.config["domain"][key] for key in CLUSTER_DOMAIN} == CLUSTER_DOMAIN

    async def test_a_run_stopped_by_the_operator_is_recorded_with_its_states(self, world):
        setup = live_setup()
        session, sent = await recording(world, setup)
        session.run_started()
        for second, scene in enumerate(setup.trajectories.scene_list[:3]):
            session.state_simulated(float(second), scene)
        session.session_ended("stopped")
        session.run_started()  # the session is over: no run follows
        await finished(session)
        assert statuses(sent)[-1] == ("saved", "entry-1", 7) and "(stopped)" in sent[-1]["message"]
        assert len(session.recordings) == 1 and world.engine.runs[0][1].steps == 2

    async def test_a_disconnect_mid_run_records_the_states_that_arrived_from_the_client_thread(self, world):
        setup = live_setup()
        session, sent = await recording(world, setup)

        def mqtt_thread():
            session.run_started()
            for second, scene in enumerate(setup.trajectories.scene_list[:4]):
                session.state_simulated(float(second), scene)

        thread = threading.Thread(target=mqtt_thread)
        thread.start()
        thread.join()
        session.session_ended("disconnected")
        session.state_simulated(4.0, setup.trajectories.scene_list[4])  # after the end: dropped
        await finished(session)
        assert statuses(sent) == [("recording", None, None), ("recording", "entry-1", None), ("saved", "entry-1", 7)]
        assert "(disconnected)" in sent[-1]["message"]
        assert len(stored_trajectories(world, world.engine.runs[0][1].state_log)) == 4

    async def test_a_run_without_a_state_stops_its_entry_and_fails(self, world):
        session, sent = await recording(world)
        session.run_started()
        session.session_ended("stopped")
        await finished(session)
        assert statuses(sent)[-1] == ("failed", "entry-1", None)
        assert sent[-1]["message"] == f"{NO_STATE_MESSAGE} (stopped), so its entry is stopped"
        assert world.engine.runs == [] and world.campaigns.desired == {"entry-1": CampaignDesiredState.STOPPED}
        assert world.announced == ["entry-1", "entry-1"]

    async def test_a_refused_recording_stops_its_entry_and_says_why(self, world):
        world.engine.error = ValueError("campaign entry-1 is not running, so it takes no recorded run")
        setup = live_setup()
        session, sent = await recording(world, setup)
        session.run_started()
        session.state_simulated(0.0, setup.trajectories.initial_scene)
        session.run_ended()
        await finished(session)
        assert statuses(sent)[-1] == ("failed", "entry-1", None)
        assert "could not be recorded (campaign entry-1 is not running, so it takes no recorded run)" in sent[-1]["message"]
        assert world.campaigns.desired == {"entry-1": CampaignDesiredState.STOPPED}

    async def test_an_entry_that_cannot_be_created_fails_the_recording(self, world):
        world.recorder.max_bytes = 100  # the loaded trajectories do not fit
        setup = live_setup()
        session, sent = await recording(world, setup)
        session.run_started()
        session.state_simulated(0.0, setup.trajectories.initial_scene)
        session.run_ended()
        await finished(session)
        assert statuses(sent) == [("recording", None, None), ("failed", None, None)]
        assert sent[-1]["message"].startswith("the workbench entry could not be created: ")
        assert world.campaigns.created == [] and world.engine.runs == []

    async def test_each_run_of_a_session_is_its_own_entry(self, world):
        setup = live_setup()
        session, sent = await recording(world, setup)
        for _ in range(2):
            session.run_started()
            session.run_started()  # a repeated start of the same run
            session.state_simulated(0.0, setup.trajectories.initial_scene)
            session.run_ended()
        await finished(session)
        assert [campaign.campaign_id for campaign in world.campaigns.created] == ["entry-1", "entry-2"]
        assert [status for status in statuses(sent) if status[0] == "saved"] == [("saved", "entry-1", 7), ("saved", "entry-2", 7)]


class StrandedCampaigns(FakeCampaigns):
    """Campaigns a previous control node process left: list_campaigns answers them, a conflict id refuses the stop."""

    def __init__(self, listed, conflict=None):
        super().__init__()
        self.listed = listed
        self.conflict = conflict
        self.asked = None

    def list_campaigns(self, actual_states=None, limit=100, offset=0, *, kinds=None, origins=None, q=None, session=None):
        self.asked = (set(actual_states), limit, list(origins))
        return self.listed

    def set_desired_state(self, campaign_id, state, expected=None, *, session=None):
        from scenegems_tool.persistence.stores import CampaignStateConflict

        if campaign_id == self.conflict:
            raise CampaignStateConflict(f"{campaign_id} completed meanwhile")
        super().set_desired_state(campaign_id, state)


@pytest.mark.anyio
class TestStrandedEntries:
    async def test_running_live_entries_without_a_case_are_stopped(self, world):
        listed = [
            SimpleNamespace(campaign_id="stranded", desired_state=CampaignDesiredState.RUNNING),
            SimpleNamespace(campaign_id="recorded", desired_state=CampaignDesiredState.RUNNING),
            SimpleNamespace(campaign_id="asked-to-stop", desired_state=CampaignDesiredState.STOPPED),
            SimpleNamespace(campaign_id="finished-meanwhile", desired_state=CampaignDesiredState.RUNNING),
        ]
        campaigns = StrandedCampaigns(listed, conflict="finished-meanwhile")
        cases = SimpleNamespace(count_cases=lambda campaign_id, **_: 1 if campaign_id == "recorded" else 0)
        announced: List[str] = []
        recorder = LiveRunRecorder(SimpleNamespace(campaigns=campaigns, cases=cases, domain=world.domain), world.artifacts, world.engine, announce=announced.extend)
        assert await recorder.stop_stranded_entries() == ["stranded"]
        assert campaigns.desired == {"stranded": CampaignDesiredState.STOPPED}
        states, limit, origins = campaigns.asked
        assert states == {state for state in CampaignActualState if not state.is_final} and limit is None and origins == [CampaignOrigin.LIVE_SESSION]
        assert announced == ["stranded"] and world.engine.wakes == 1

    async def test_nothing_stranded_changes_nothing(self, world):
        recorder = LiveRunRecorder(SimpleNamespace(campaigns=StrandedCampaigns([]), cases=None, domain=world.domain), world.artifacts, world.engine)
        assert await recorder.stop_stranded_entries() == [] and world.engine.wakes == 0


@pytest.mark.anyio
class TestStandaloneGateway:
    async def test_without_a_recorder_every_run_is_reported_unavailable_once(self, world):
        session, sent = await recording(world, recorder=None)
        session.run_started()
        session.run_started()
        session.state_simulated(0.0, live_setup().trajectories.initial_scene)
        session.run_ended()
        session.run_started()
        session.session_ended("stopped")
        await settle()
        assert sent == [{"type": "run_recording", "status": "unavailable", "campaignId": None, "caseId": None, "message": UNAVAILABLE_MESSAGE}] * 2
        assert session.recordings == []


class TestSetup:
    def test_the_environment_has_the_shape_of_a_campaign_run(self):
        environment = EnvironmentConfig(wind_vector=np.array([1.0, 2.0, 0.0]), wave=WaveConfig(amplitude=0.5, period=4.0, steepness=0.1, direction=np.array([0.0, 1.0])))
        assert environment_settings(environment) == {"wind_vector": [1.0, 2.0, 0.0], "waves": {"amplitude": 0.5, "period": 4.0, "steepness": 0.1, "direction": [0.0, 1.0]}}
        assert environment_settings(EnvironmentConfig.calm()) == {"wind_vector": [0.0, 0.0, 0.0], "waves": None}

    def test_a_real_vessel_has_no_repeatability_and_no_agent_stack_is_invented(self):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        config.vessels["1"].context = AgentContext.REAL
        config.vessels["1"].stack = VesselStackConfig(AsvSystemId.MISSION_PLANNER, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
        config.vessels["1"].adapter_ids = ()
        setup = live_setup(config)
        assert setup.repeatability_tier() == "none"
        assert setup.stack()["vessels"]["1"]["context"] == "real" and setup.stack()["vessels"]["1"]["simulation_layer"] == "real_vessel"


# On the control node: Postgres stores and the real pipeline engine

from tests.scenegems_tool.assurance.pipeline.conftest import clock, loop, make_harness  # noqa: E402,F401 (fixtures)


def control_node_world(make_harness, session_factory, tmp_path):  # noqa: F811 (the fixture)
    from scenegems_tool.persistence.stores import ArtifactRecordStore

    harness = make_harness(references=True)
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), ArtifactRecordStore(session_factory))
    recorder = LiveRunRecorder(harness.stores, artifacts, harness.engine)
    return harness, artifacts, recorder


def record(harness, recorder, setup, scenes, end):
    """A live run on the harness's loop: started, its states, then its end; the session and its messages."""
    sent: List[dict] = []
    session = LiveSessionRecording(recorder, setup, harness.loop, sent.append)
    session.run_started()
    for second, scene in enumerate(scenes):
        session.state_simulated(float(second), scene)
    end(session)

    async def done():
        for run in session.recordings:
            await asyncio.wrap_future(run.future)
        await settle()

    harness.run(done())
    return session, sent


@pytest.mark.postgres
class TestOnTheControlNode:
    def test_a_recorded_live_run_is_judged_by_the_post_hoc_monitor(self, make_harness, session_factory, tmp_path):  # noqa: F811 (the fixture)
        harness, artifacts, recorder = control_node_world(make_harness, session_factory, tmp_path)
        setup = live_setup()
        _, sent = record(harness, recorder, setup, setup.trajectories.scene_list[:10], lambda session: session.run_ended())
        saved = sent[-1]
        assert (saved["status"], saved["caseId"] is not None) == ("saved", True), sent
        campaign_id = saved["campaignId"]
        campaign = harness.campaign(campaign_id)
        assert (campaign.kind, campaign.origin) == (CampaignKind.WORKBENCH, CampaignOrigin.LIVE_SESSION)
        (record_,) = harness.stores.results.list_run_records(campaign_id)
        assert record_.stack["config"]["simulation_layer"] == "ardupilot_sim" and record_.steps == 9 and record_.dt == 1.0
        for sha256 in record_.artifacts.values():  # the fake executor reads the monitor's input from its own store
            harness.executor.artifacts.documents[sha256] = artifacts.store.read(sha256)
        assert harness.drive(campaign_id).actual_state == CampaignActualState.COMPLETED
        (verdict,) = harness.stores.results.list_verdicts(campaign_id)
        assert verdict.run_record_id == record_.run_record_id and verdict.state.value in ("passed", "failed")
        assert sorted(reference.role for reference in artifacts.records.references_of(ArtifactHolderKind.RUN, str(record_.run_record_id))) == ["frames", "state_log"]
        references = {(reference.holder_kind, reference.role) for reference in artifacts.records.references(record_.artifacts["trajectories"])}
        assert (ArtifactHolderKind.CAMPAIGN, INPUT_ROLE) in references

    def test_a_restart_stops_the_live_entries_left_without_a_run(self, make_harness, session_factory, tmp_path):  # noqa: F811 (the fixture)
        harness, _, recorder = control_node_world(make_harness, session_factory, tmp_path)
        setup = live_setup()
        stranded = recorder._open(setup).campaign_id  # opened, then the control node process stopped before its run ended
        _, sent = record(harness, recorder, setup, setup.trajectories.scene_list[:5], lambda session: session.run_ended())
        recorded = sent[-1]["campaignId"]
        assert harness.run(recorder.stop_stranded_entries()) == [stranded]
        harness.settle()
        assert harness.campaign(stranded).actual_state == CampaignActualState.STOPPED
        assert harness.campaign(recorded).desired_state == CampaignDesiredState.RUNNING  # its recorded run finishes it
        assert harness.run(recorder.stop_stranded_entries()) == []

    def test_a_live_run_without_a_state_leaves_a_stopped_entry(self, make_harness, session_factory, tmp_path):  # noqa: F811 (the fixture)
        harness, _, recorder = control_node_world(make_harness, session_factory, tmp_path)
        _, sent = record(harness, recorder, live_setup(), [], lambda session: session.session_ended("disconnected"))
        assert sent[-1]["status"] == "failed"
        campaign_id = sent[-1]["campaignId"]
        harness.settle()
        assert harness.campaign(campaign_id).actual_state == CampaignActualState.STOPPED
        assert harness.stores.cases.list_cases(campaign_id) == []
