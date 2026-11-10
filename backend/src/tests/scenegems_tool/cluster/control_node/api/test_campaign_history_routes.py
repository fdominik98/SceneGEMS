"""The Phase 6 campaign routes on a real Postgres (-m postgres): kind and origin, the list rows, delete, outputs, findings and the step filters."""

import csv
import io
import json

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_operator_app
from scenegems_tool.cluster.control_node.control_node_artifacts import ControlNodeArtifacts
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, CAMPAIGNS_PATH
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.schema import CampaignActualState, CaseState, MonitorImplementation, PipelineStage, RunSource, StepKind, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NewCase, NewRunRecord, NewVerdict, WorkerNodeStore
from tests.scenegems_tool.cluster.control_node.api.test_campaign_routes import CLASS_A, CLASS_B, JSON, YAML, small_config
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED
from tests.scenegems_tool.cluster.control_node.live.live_browser import LiveBrowser
from tests.scenegems_tool.persistence.stores.builders import ManualClock

pytestmark = pytest.mark.postgres

SCENE_0 = "a0" * 32
SCENE_1 = "a1" * 32
TRAJECTORY_DATA_0 = "b0" * 32
STATE_LOG_0 = "c0" * 32
GONE_CAMPAIGN = "00000000-0000-0000-0000-000000000000"


def scene_document(vessels: int = 2, obstacles: int = 1) -> dict:
    def actor(actor_id: int, vessel: bool) -> list:
        return [{"id": actor_id, "type": "MiniUSV" if vessel else "Buoy", "is_vessel": vessel}, {"x": 0.0, "y": 0.0}]

    return {"_data": [actor(index, True) for index in range(vessels)] + [actor(vessels + index, False) for index in range(obstacles)], "dcpa": None}


def partial_config(steps, **changes) -> str:
    """The small exit campaign as a format 2 config running some steps."""
    return small_config(format=2, name="partial", steps=steps, **changes)


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


@pytest.fixture
def plane(session_factory, clock) -> ControlPlane:
    worker_nodes = WorkerNodeStore(session_factory, clock)
    return ControlPlane("lab-control-node", worker_nodes, JobStore(session_factory, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def artifacts(tmp_path, stores) -> ControlNodeArtifacts:
    return ControlNodeArtifacts(RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), stores.artifacts))


@pytest.fixture
def client(plane, stores, artifacts):
    with TestClient(create_operator_app(plane, assurance=stores, artifacts=artifacts)) as client:
        yield client


def create(client, text=None, **query):
    return client.post(CAMPAIGNS_PATH, content=small_config() if text is None else text, headers=YAML, params=query)


def upload(client, document: dict, kind: str = "scene") -> dict:
    response = client.post(ARTIFACTS_PATH, content=json.dumps(document), headers=JSON, params={"kind": kind})
    assert response.status_code == 201, response.text
    return response.json()


OVERTAKING_ROLES = {"OS_0 - TS_1": {"OVERTAKING_TO_PORT": {"give_way": ["TS_1"], "stand_on": ["OS_0"]}}}


def seed_outputs(stores, campaign_id):
    """Class A: case 0 completed every step (scene, trajectories and the run 0 verdicts, runs 0 and 1), case 1 dropped with an invalid scene. Class B: case 0 still generating."""
    a0, a1 = stores.cases.create_cases(campaign_id, [NewCase(CLASS_A, 0, 100), NewCase(CLASS_A, 1, 101)])
    (b0,) = stores.cases.create_cases(campaign_id, [NewCase(CLASS_B, 0, 200)])
    for sha, kind in ((SCENE_0, "scene"), (TRAJECTORY_DATA_0, "trajectory_data"), (STATE_LOG_0, "trajectories")):
        stores.artifacts.insert_if_absent(sha, kind, 100, "application/json")
    a0 = stores.cases.move_case(
        a0.case_id, a0.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE, scene_artifact=SCENE_0, trajectories_artifact=TRAJECTORY_DATA_0, trajectories_complete=True
    )
    stores.cases.move_case(a1.case_id, a1.version, state=CaseState.DROPPED, scene_artifact=SCENE_1, reason="the scene generation found no valid scene")
    runs = [stores.results.add_run_record(NewRunRecord(a0.case_id, index, None, True, {}, {}, 5, artifacts={"state_log": STATE_LOG_0})) for index in (0, 1)]
    post_hoc = MonitorImplementation.POST_HOC
    stores.results.add_verdict(NewVerdict(a0.case_id, 0, VerdictState.PASSED, post_hoc, step=StepKind.SCENE, encounters={"OS_0 - TS_1": ["HEAD_ON", "OTHER"], "OS_0 - TS_2": ["OTHER"]}))
    stores.results.add_verdict(
        NewVerdict(
            a0.case_id,
            0,
            VerdictState.FAILED,
            post_hoc,
            failed_rules=("OS_0 - TS_1: rule_13",),
            rule_outcomes={"OS_0 - TS_1": {"rule_13": {"failed": 12.0}}},
            first_failure_time_s=12.0,
            step=StepKind.TRAJECTORIES,
        )
    )
    stores.results.add_verdict(
        NewVerdict(
            a0.case_id,
            0,
            VerdictState.FAILED,
            post_hoc,
            failed_rules=("OS_0 - TS_1: rule_8",),
            rule_outcomes={"OS_0 - TS_1": {"rule_8": {"failed": 4.0}}},
            first_failure_time_s=4.0,
            run_record_id=runs[0].run_record_id,
            encounters={"OS_0 - TS_1": ["OVERTAKING_TO_PORT"]},
            encounter_roles=OVERTAKING_ROLES,
        )
    )
    stores.results.add_verdict(NewVerdict(a0.case_id, 1, VerdictState.PASSED, post_hoc, run_record_id=runs[1].run_record_id))
    return a0, a1, b0, runs


# Create


def test_a_campaign_made_without_kind_and_origin_is_a_campaign_without_origin(client):
    view = create(client).json()
    assert view["kind"] == "campaign" and view["origin"] is None
    assert view["steps"] == ["scene_generation", "trajectory_generation", "simulation"] and view["input"] == {"first_step": "scene_generation", "item_count": 0} and view["made_from"] == []


def test_kind_and_origin_come_from_the_query_of_a_yaml_body_or_from_a_json_body(client):
    view = create(client, kind="workbench", origin="trajectory_generation").json()
    assert (view["kind"], view["origin"]) == ("workbench", "trajectory_generation")
    wizard = client.post(CAMPAIGNS_PATH, json={"config": small_config(), "kind": "campaign", "origin": "wizard"}).json()
    assert (wizard["kind"], wizard["origin"]) == ("campaign", "wizard")
    assert create(client, origin="cli").json()["kind"] == "campaign"  # the origin implies its kind
    assert create(client, origin="live_session").json()["kind"] == "workbench"
    assert client.post(CAMPAIGNS_PATH, json={"config": small_config(), "origin": "simulation"}, params={"origin": "scene_generation"}).json()["origin"] == "scene_generation"  # the query wins


@pytest.mark.parametrize(
    "query, fragment",
    [
        ({"kind": "batch"}, '"kind" is one of campaign, workbench'),
        ({"origin": "somewhere"}, '"origin" is one of wizard'),
        ({"kind": "campaign", "origin": "simulation"}, 'origin "simulation" belongs to kind "workbench"'),
        ({"kind": "workbench", "origin": "wizard"}, 'origin "wizard" belongs to kind "campaign"'),
    ],
)
def test_a_kind_or_origin_that_is_unknown_or_does_not_fit_answers_422(client, stores, query, fragment):
    response = create(client, **query)
    assert response.status_code == 422 and fragment in " ".join(response.json()["detail"]["reasons"])
    assert stores.campaigns.list_campaigns() == []


def test_kind_and_origin_do_not_change_the_config_hash(client, stores):
    first, second = create(client, origin="wizard").json(), create(client, kind="workbench", origin="simulation").json()
    versions = [stores.campaigns.config_version(view["campaign_id"]) for view in (first, second)]
    assert versions[0].config_hash == versions[1].config_hash and "kind" not in versions[0].config and "origin" not in versions[0].config


def test_creating_wakes_the_pipeline_engine_when_the_plane_can(client, plane):
    woken = []
    plane.wake_pipeline = lambda: woken.append(1)
    create(client)
    assert woken == [1]
    awaited = []

    async def wake():
        awaited.append(1)

    plane.wake_pipeline = wake
    create(client)
    assert awaited == [1]


def test_creating_works_on_a_plane_without_a_wake(client, plane):
    assert create(client).status_code == 201


def test_a_failed_create_does_not_wake_the_engine(client, plane):
    woken = []
    plane.wake_pipeline = lambda: woken.append(1)
    assert create(client, "scope: [").status_code == 422
    assert woken == []


def test_a_partial_campaign_creates_with_its_steps_and_monitor(client, stores):
    view = create(client, partial_config(["scene_generation", "trajectory_generation"], scene_generation={"monitor": "post_hoc"})).json()
    assert view["steps"] == ["scene_generation", "trajectory_generation"]
    assert stores.campaigns.config_version(view["campaign_id"]).config["scene_generation"]["monitor"] == "post_hoc"


def test_the_input_is_checked_against_the_artifact_store_and_made_from_follows_the_sources(client):
    scene = upload(client, scene_document())
    source = {"campaign_id": "c1", "case_id": 5, "step": "scene_generation"}
    items = [
        {"name": "case 5", "ref": scene, "source": source},
        {"name": "a file", "ref": scene, "source": {"file": "scene.json"}},
        {"name": "case 6", "ref": scene, "source": {**source, "case_id": 6}},
    ]
    view = create(client, partial_config(["trajectory_generation"], scope=[], input={"items": items})).json()
    assert view["input"] == {"first_step": "trajectory_generation", "item_count": 3} and view["made_from"] == ["c1"]
    assert [entry["fec_id"] for entry in view["fecs"]] == ["item/0", "item/1", "item/2"]
    listed = client.get(CAMPAIGNS_PATH).json()[0]
    assert listed["input"] == view["input"] and listed["made_from"] == ["c1"] and listed["steps"] == ["trajectory_generation"]


def test_an_item_whose_artifact_is_missing_answers_422(client):
    missing = {"sha256": "ee" * 32, "size_bytes": 10, "kind": "scene", "media_type": "application/json"}
    response = create(client, partial_config(["trajectory_generation"], scope=[], input={"items": [{"name": "gone", "ref": missing, "source": {"file": "x.json"}}]}))
    assert response.status_code == 422 and "no artifact" in " ".join(response.json()["detail"]["reasons"])


def test_validating_checks_the_input_against_the_artifact_store_too(client):
    scene = upload(client, scene_document())
    text = partial_config(["trajectory_generation"], scope=[], input={"items": [{"name": "case 5", "ref": scene, "source": {"file": "x.json"}}]})
    validated = client.post(f"{CAMPAIGNS_PATH}/validate", content=text, headers=YAML).json()
    assert validated["valid"] is True and [entry["fec_id"] for entry in validated["fecs"]] == ["item/0"]


def test_a_control_node_without_an_artifact_store_refuses_a_config_with_input(plane, stores):
    scene = {"sha256": "ee" * 32, "size_bytes": 10, "kind": "scene", "media_type": "application/json"}
    text = partial_config(["trajectory_generation"], scope=[], input={"items": [{"name": "x", "ref": scene, "source": {"file": "x.json"}}]})
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        response = create(client, text)
    assert response.status_code == 422 and "no artifact store" in " ".join(response.json()["detail"]["reasons"])


# List


def test_a_list_row_carries_the_totals_and_the_config_fields(client, stores):
    campaign_id = create(client, origin="wizard").json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    (row,) = client.get(CAMPAIGNS_PATH).json()
    assert row["campaign_id"] == campaign_id and row["kind"] == "campaign" and row["origin"] == "wizard"
    assert row["totals"] == {
        "cases": {"active": 1, "complete": 1, "dropped": 1},
        "verdicts": {"scene": {"passed": 1}, "trajectories": {"failed": 1}, "simulation": {"failed": 1, "passed": 1}},
    }
    assert "fecs" not in row  # the detail has the classes, the row stays small


def test_the_list_filters_by_kind_origin_name_and_state_and_counts_the_matches(client, stores):
    wizard = create(client, name="Head-on batch", origin="wizard").json()["campaign_id"]
    cli = create(client, name="Overtaking", origin="cli").json()["campaign_id"]
    scene = create(client, name="Scene run", origin="scene_generation").json()["campaign_id"]
    simulation = create(client, name="Simulation run", origin="simulation").json()["campaign_id"]
    stores.campaigns.set_actual_state(simulation, CampaignActualState.RUNNING)

    def ids(**params):
        response = client.get(CAMPAIGNS_PATH, params=params)
        assert int(response.headers["x-total-count"]) == len(response.json()) or "limit" in params
        return {row["campaign_id"] for row in response.json()}, int(response.headers["x-total-count"])

    assert ids(kind="campaign") == ({wizard, cli}, 2)
    assert ids(kind="workbench") == ({scene, simulation}, 2)
    assert ids(origin="cli") == ({cli}, 1)
    assert ids(origin=["cli", "simulation"]) == ({cli, simulation}, 2)
    assert ids(q="HEAD") == ({wizard}, 1)
    assert ids(q="run") == ({scene, simulation}, 2)
    assert ids(q="100%") == (set(), 0)  # a percent sign is taken literally
    assert ids(kind="workbench", state="running") == ({simulation}, 1)
    assert ids(kind="workbench", limit=1)[1] == 2  # the total counts the filter, not the page
    assert ids(q="")[1] == 4
    assert client.get(CAMPAIGNS_PATH, params={"kind": "bogus"}).status_code == 422
    assert client.get(CAMPAIGNS_PATH, params={"origin": "bogus"}).status_code == 422


def test_a_campaign_made_before_phase_six_lists_without_an_origin(client, stores, session_factory):
    from sqlalchemy import text

    campaign_id = create(client).json()["campaign_id"]
    with session_factory() as session, session.begin():
        session.execute(text("update campaign set origin = null where id = :id"), {"id": campaign_id})
    (row,) = client.get(CAMPAIGNS_PATH).json()
    assert row["origin"] is None and row["kind"] == "campaign"


# Show


def test_the_detail_carries_kind_origin_and_the_config_fields(client):
    created = create(client, partial_config(["scene_generation"]), origin="cli").json()
    detail = client.get(f"{CAMPAIGNS_PATH}/{created['campaign_id']}").json()
    assert (detail["kind"], detail["origin"], detail["steps"], detail["input"]) == ("campaign", "cli", ["scene_generation"], {"first_step": "scene_generation", "item_count": 0})
    assert detail["totals"]["fecs"] == 2 and "cases" not in detail["totals"]  # the detail keeps its own totals


# Delete


def test_deleting_a_final_campaign_answers_204_and_removes_it(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    stores.campaigns.set_actual_state(campaign_id, CampaignActualState.COMPLETED)
    response = client.delete(f"{CAMPAIGNS_PATH}/{campaign_id}")
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}").status_code == 404
    assert client.get(CAMPAIGNS_PATH).json() == []
    assert client.delete(f"{CAMPAIGNS_PATH}/{campaign_id}").status_code == 404


@pytest.mark.parametrize("state", [CampaignActualState.CREATED, CampaignActualState.RUNNING, CampaignActualState.STALLED])
def test_deleting_a_campaign_that_is_not_final_answers_409(client, stores, state):
    campaign_id = create(client).json()["campaign_id"]
    stores.campaigns.set_actual_state(campaign_id, state)
    response = client.delete(f"{CAMPAIGNS_PATH}/{campaign_id}")
    assert response.status_code == 409 and "only a stopped or completed campaign can be deleted" in response.json()["detail"]
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}").status_code == 200


def test_a_stopped_campaign_is_deleted_and_its_artifacts_are_released(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    stores.campaigns.set_actual_state(campaign_id, CampaignActualState.STOPPED)
    assert client.delete(f"{CAMPAIGNS_PATH}/{campaign_id}").status_code == 204


def test_deleting_an_unknown_campaign_answers_404(client):
    assert client.delete(f"{CAMPAIGNS_PATH}/no-such").status_code == 404


def test_a_control_node_without_stores_answers_503_to_a_delete(plane):
    with TestClient(create_operator_app(plane)) as client:
        assert client.delete(f"{CAMPAIGNS_PATH}/c1").status_code == 503


# Outputs


def test_outputs_list_the_cases_of_a_step_with_the_verdict_and_the_artifact(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    a0, a1, b0, _runs = seed_outputs(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/outputs"

    scenes = client.get(path, params={"step": "scene_generation"})
    assert scenes.status_code == 200 and scenes.headers["x-total-count"] == "3"
    first, dropped, running = scenes.json()
    assert first["case_id"] == a0.case_id and first["fec_id"] == CLASS_A and first["case_index"] == 0 and first["state"] == "complete"
    assert first["artifact"] == {"sha256": SCENE_0, "size_bytes": 100, "kind": "scene", "media_type": "application/json", "pointer": None}
    assert first["valid"] is True and first["complete"] is None
    assert first["verdict"] == {
        "state": "passed",
        "failed_rules": [],
        "first_failure_time_s": None,
        "encounters": {"OS_0 - TS_1": ["HEAD_ON", "OTHER"], "OS_0 - TS_2": ["OTHER"]},
        "encounter_roles": None,
    }
    assert (first["run_index"], first["repeat_index"], first["run_record_id"], first["input_source"]) == (None, None, None, None)
    assert dropped["case_id"] == a1.case_id and dropped["valid"] is False and dropped["reason"] == "the scene generation found no valid scene"
    assert dropped["artifact"] is None  # the invalid scene has no artifact record
    assert running["case_id"] == b0.case_id and running["artifact"] is None and running["verdict"] is None

    (trajectories,) = client.get(path, params={"step": "trajectory_generation"}).json()[:1]
    assert trajectories["artifact"]["kind"] == "trajectory_data" and trajectories["artifact"]["pointer"] == "/trajectories"
    assert trajectories["complete"] is True
    assert trajectories["verdict"] == {"state": "failed", "failed_rules": ["OS_0 - TS_1: rule_13"], "first_failure_time_s": 12.0, "encounters": None, "encounter_roles": None}


def test_simulation_outputs_are_one_row_per_run_with_its_record_and_verdict(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    a0, _a1, _b0, runs = seed_outputs(stores, campaign_id)
    response = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/outputs", params={"step": "simulation", "fec_id": CLASS_A})
    assert response.headers["x-total-count"] == "2"
    first, second = response.json()
    assert [(row["run_index"], row["repeat_index"], row["run_record_id"]) for row in (first, second)] == [(0, 0, runs[0].run_record_id), (1, 0, runs[1].run_record_id)]
    assert first["artifact"]["sha256"] == STATE_LOG_0 and first["artifact"]["kind"] == "trajectories" and first["artifact"]["pointer"] is None
    assert first["verdict"] == {
        "state": "failed",
        "failed_rules": ["OS_0 - TS_1: rule_8"],
        "first_failure_time_s": 4.0,
        "encounters": {"OS_0 - TS_1": ["OVERTAKING_TO_PORT"]},
        "encounter_roles": OVERTAKING_ROLES,
    }
    assert second["verdict"] == {"state": "passed", "failed_rules": [], "first_failure_time_s": None, "encounters": None, "encounter_roles": None}


def test_the_verdict_route_carries_the_vessel_roles(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    verdicts = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"step": "simulation"}).json()
    assert [verdict["encounter_roles"] for verdict in verdicts] == [OVERTAKING_ROLES, None]


def test_outputs_are_filtered_by_state_and_paged(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/outputs"
    dropped = client.get(path, params={"step": "scene_generation", "state": "dropped"})
    assert [row["state"] for row in dropped.json()] == ["dropped"] and dropped.headers["x-total-count"] == "1"
    both = client.get(path, params={"step": "scene_generation", "state": ["dropped", "active"]})
    assert both.headers["x-total-count"] == "2"
    page = client.get(path, params={"step": "scene_generation", "limit": 1, "offset": 1})
    assert len(page.json()) == 1 and page.headers["x-total-count"] == "3"
    assert client.get(path, params={"step": "scene_generation", "fec_id": CLASS_B}).headers["x-total-count"] == "1"
    assert client.get(path, params={"step": "scene_generation", "state": "bogus"}).status_code == 422


def test_an_input_source_reads_empty_once_its_campaign_was_deleted(client, stores):
    source = create(client).json()["campaign_id"]
    stores.campaigns.set_actual_state(source, CampaignActualState.COMPLETED)
    scene = upload(client, scene_document())
    items = [
        {"name": "from the source", "ref": scene, "source": {"campaign_id": source, "case_id": 1, "step": "scene_generation"}},
        {"name": "from a file", "ref": scene, "source": {"file": "scene.json"}},
    ]
    made = create(client, partial_config(["trajectory_generation"], scope=[], input={"items": items})).json()["campaign_id"]
    created = stores.cases.create_cases(
        made,
        [NewCase("item/0", 0, 1, input_artifact=scene["sha256"], input_source=items[0]["source"]), NewCase("item/1", 0, 2, input_artifact=scene["sha256"], input_source=items[1]["source"])],
    )
    for case in created:  # the first step of this campaign is trajectory generation
        stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.GENERATE_TRAJECTORIES)
    detail = client.get(f"{CAMPAIGNS_PATH}/{made}/cases/{created[1].case_id}").json()
    assert (detail["input_artifact"], detail["input_source"]) == (scene["sha256"], {"file": "scene.json"})  # what the case started from
    path = f"{CAMPAIGNS_PATH}/{made}/outputs"
    sources = [row["input_source"] for row in client.get(path, params={"step": "trajectory_generation"}).json()]
    assert sources == [items[0]["source"], {"file": "scene.json"}]
    assert client.delete(f"{CAMPAIGNS_PATH}/{source}").status_code == 204
    sources = [row["input_source"] for row in client.get(path, params={"step": "trajectory_generation"}).json()]
    assert sources == [{}, {"file": "scene.json"}]


def test_outputs_need_a_known_step_that_the_campaign_runs(client, stores):
    campaign_id = create(client, partial_config(["scene_generation"])).json()["campaign_id"]
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/outputs"
    assert client.get(path).status_code == 422  # no step
    assert client.get(path, params={"step": "scene"}).status_code == 422  # the verdict step name is not an API step
    refused = client.get(path, params={"step": "simulation"})
    assert refused.status_code == 422 and "does not run simulation" in refused.json()["detail"]
    assert client.get(path, params={"step": "scene_generation"}).json() == []
    assert client.get(f"{CAMPAIGNS_PATH}/no-such/outputs", params={"step": "simulation"}).status_code == 404


# Findings


def test_findings_summarize_a_step(client, stores):
    campaign_id = create(client, partial_config(["scene_generation", "trajectory_generation", "simulation"], scene_generation={"monitor": "post_hoc"})).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/findings"

    scene = client.get(path, params={"step": "scene_generation"}).json()
    assert scene["step"] == "scene_generation" and scene["monitored"] is True  # the config monitors the scenes
    assert scene["cases"] == {"active": 1, "complete": 1, "dropped": 1} and scene["outputs"] == {"count": 2, "valid": 1, "complete": 1}  # the case still generating has no output yet
    assert scene["verdicts"] == {"passed": 1, "failed": 0, "unmonitored": 0} and scene["failed_rules"] == []
    assert scene["encounter_types"] == {"HEAD_ON": 1, "OTHER": 1}  # the pairs by their first encounter type, OTHER included
    assert {entry["fec_id"]: (entry["cases"], entry["passed"], entry["failed"]) for entry in scene["fecs"]}[CLASS_A] == (2, 1, 0)

    trajectories = client.get(path, params={"step": "trajectory_generation"}).json()
    assert trajectories["monitored"] is False  # the config's trajectory monitor is empty: statistics only, whatever the rows hold
    assert trajectories["verdicts"] == {"passed": 0, "failed": 0, "unmonitored": 0} and trajectories["failed_rules"] == [] and trajectories["encounter_types"] == {}
    assert trajectories["durations_s"] == {"median": None, "p90": None}

    simulation = client.get(path, params={"step": "simulation"}).json()
    assert simulation["monitored"] is True and simulation["verdicts"] == {"passed": 1, "failed": 1, "unmonitored": 0}
    assert simulation["encounter_types"] == {"OVERTAKING_TO_PORT": 1}
    assert simulation["failed_rules"] == [{"rule": "rule_8", "count": 1, "first_failure_time_s": {"min": 4.0, "median": 4.0}}]


def test_findings_use_the_config_to_tell_whether_a_step_is_monitored(client, stores):
    monitored = create(client, partial_config(["scene_generation", "trajectory_generation"], trajectories={"generator": "straight", "timespan_s": 60, "monitor": "post_hoc"})).json()["campaign_id"]
    seed_outputs(stores, monitored)
    findings = client.get(f"{CAMPAIGNS_PATH}/{monitored}/findings", params={"step": "trajectory_generation"}).json()
    assert findings["monitored"] is True and findings["verdicts"] == {"passed": 0, "failed": 1, "unmonitored": 0}
    assert findings["failed_rules"] == [{"rule": "rule_13", "count": 1, "first_failure_time_s": {"min": 12.0, "median": 12.0}}]


def test_findings_need_a_known_step_that_the_campaign_runs(client):
    campaign_id = create(
        client,
        partial_config(
            ["simulation"], scope=[], input={"items": [{"name": "t", "ref": upload(client, {"scene_list": [scene_document()], "time_step": 5}, "trajectories"), "source": {"file": "t.json"}}]}
        ),
    ).json()["campaign_id"]
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/findings"
    assert client.get(path).status_code == 422
    assert client.get(path, params={"step": "trajectories"}).status_code == 422
    assert "does not run scene_generation" in client.get(path, params={"step": "scene_generation"}).json()["detail"]
    assert client.get(path, params={"step": "simulation"}).status_code == 200
    assert client.get(f"{CAMPAIGNS_PATH}/no-such/findings", params={"step": "simulation"}).status_code == 404


# Verdicts and run records


def test_verdicts_carry_their_step_and_filter_on_it(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts"
    every = client.get(path)
    assert [(row["step"], row["run_index"]) for row in every.json()] == [("scene", 0), ("trajectories", 0), ("simulation", 0), ("simulation", 1)]
    for step, count in (("scene", 1), ("trajectories", 1), ("simulation", 2)):
        response = client.get(path, params={"step": step})
        assert len(response.json()) == count and response.headers["x-total-count"] == str(count) and {row["step"] for row in response.json()} == {step}
    assert client.get(path, params={"step": "trajectories", "state": "passed"}).json() == []
    assert client.get(path, params={"step": "scene_generation"}).status_code == 422  # the verdict step names are scene, trajectories and simulation


def test_the_verdict_csv_has_a_step_column_and_filters_on_it(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_outputs(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts"
    rows = list(csv.DictReader(io.StringIO(client.get(path, params={"format": "csv"}).text)))
    assert [row["step"] for row in rows] == ["scene", "trajectories", "simulation", "simulation"]
    only = client.get(path, params={"format": "csv", "step": "simulation", "limit": 1})
    assert [row["step"] for row in csv.DictReader(io.StringIO(only.text))] == ["simulation"]


def test_run_records_carry_their_source_and_may_have_no_generator(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    a0, _a1, _b0, _runs = seed_outputs(stores, campaign_id)
    stores.results.add_run_record(NewRunRecord(a0.case_id, 2, None, True, {}, {}, 5, source=RunSource.LIVE_SESSION))
    records = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/run-records").json()
    assert [(record["run_index"], record["source"], record["trajectory_generator"]) for record in records] == [(0, "job", None), (1, "job", None), (2, "live_session", None)]
    detail = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases/{a0.case_id}").json()
    assert {record["source"] for record in detail["run_records"]} == {"job", "live_session"}
    assert {verdict["step"] for verdict in detail["verdicts"]} == {"scene", "trajectories", "simulation"}


# The campaigns topic of the live channel


def test_the_campaigns_topic_hears_of_creates_controls_and_deletes_from_the_routes(client, stores):
    browser = LiveBrowser(client)
    try:
        assert browser.subscribe("campaigns") == {}
        created = create(client, origin="wizard", name="watched").json()
        row = browser.expect_update("campaigns")["campaign"]
        assert (row["campaign_id"], row["name"], row["origin"], row["desired_state"]) == (created["campaign_id"], "watched", "wizard", "paused")
        assert row["totals"] == {"cases": {}, "verdicts": {}}

        client.post(f"{CAMPAIGNS_PATH}/{created['campaign_id']}/start")
        assert browser.expect_update("campaigns")["campaign"]["desired_state"] == "running"

        stores.campaigns.set_actual_state(created["campaign_id"], CampaignActualState.STOPPED)
        assert client.delete(f"{CAMPAIGNS_PATH}/{created['campaign_id']}").status_code == 204
        assert browser.expect_update("campaigns") == {"deleted": created["campaign_id"]}
        assert browser.drain() == []  # nothing else was sent
    finally:
        browser.close()


def test_a_refused_delete_and_a_failed_create_send_nothing(client, stores):
    browser = LiveBrowser(client)
    try:
        browser.subscribe("campaigns")
        campaign_id = create(client).json()["campaign_id"]
        browser.expect_update("campaigns")
        assert client.delete(f"{CAMPAIGNS_PATH}/{campaign_id}").status_code == 409
        assert create(client, "scope: [").status_code == 422
        assert browser.drain() == []
    finally:
        browser.close()


# Design space exploration

EXPLORING = {
    "format": 3,
    "name": "explore",
    "steps": ["design_space_exploration", "scene_generation"],
    "design_space_exploration": {"specification": "class OS.\nclass TS.\n", "scope": "TS = 1..2"},
}


def create_exploring(client, **changes):
    response = client.post(CAMPAIGNS_PATH, content=json.dumps({"config": {**EXPLORING, **changes}, "kind": "workbench", "origin": "design_space_exploration"}), headers=JSON)
    assert response.status_code == 201, response.text
    return response.json()


def seed_explored(stores, campaign_id, texts=("OS(os).\nTS(ts1).\n", "OS(os).\nTS(ts1).\nTS(ts2).\n")):
    """The exploration case, complete, and one class per text with its artifact record, as the engine leaves them."""
    import hashlib

    from scenegems_tool.assurance.campaign.campaign_config import DesignSpaceExplorationConfig
    from scenegems_tool.assurance.campaign.campaign_inputs import explored_class_spec
    from scenegems_tool.subsystems.design_space_exploration.design_space import count_instances

    (exploration,) = stores.cases.create_cases(campaign_id, [NewCase("exploration", 0, 7, stage=PipelineStage.EXPLORE_DESIGN_SPACE)])
    section = DesignSpaceExplorationConfig(**EXPLORING["design_space_exploration"])
    specs = []
    for index, text in enumerate(texts):
        data = text.encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        stores.artifacts.insert_if_absent(sha, "functional_scenario", len(data), "text/plain; charset=utf-8")
        specs.append(explored_class_spec(index, sha, *count_instances(text), section))
    stores.cases.add_classes(campaign_id, specs)
    stores.cases.move_case(exploration.case_id, exploration.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    return exploration, specs


def test_an_exploring_entry_is_created_with_its_origin_and_first_step(client, stores):
    created = create_exploring(client)
    assert (created["kind"], created["origin"], created["steps"], created["input"]) == (
        "workbench",
        "design_space_exploration",
        EXPLORING["steps"],
        {"first_step": "design_space_exploration", "item_count": 0},
    )
    (record,) = stores.cases.list_classes(created["campaign_id"])
    assert (record.class_id, record.vessel_count) == ("exploration", 0)
    listed = client.get(CAMPAIGNS_PATH, params={"origin": "design_space_exploration"})
    assert [row["campaign_id"] for row in listed.json()] == [created["campaign_id"]]


def test_the_outputs_of_the_exploration_are_the_fecs_it_found(client, stores):
    campaign_id = create_exploring(client)["campaign_id"]
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/outputs"
    empty = client.get(path, params={"step": "design_space_exploration"})
    assert (empty.status_code, empty.json(), empty.headers["x-total-count"]) == (200, [], "0")  # nothing until the exploration has finished
    exploration, specs = seed_explored(stores, campaign_id)
    response = client.get(path, params={"step": "design_space_exploration"})
    assert response.status_code == 200 and response.headers["x-total-count"] == "2"
    first, second = response.json()
    assert first == {
        "case_id": exploration.case_id,
        "case_index": 0,
        "fec_id": "explored/00000",
        "state": "complete",
        "reason": None,
        "artifact": {"sha256": specs[0].content_hash, "size_bytes": 17, "kind": "functional_scenario", "media_type": "text/plain; charset=utf-8", "pointer": None},
        "valid": True,
        "complete": None,
        "run_index": None,
        "repeat_index": None,
        "run_record_id": None,
        "verdict": None,
        "input_source": None,
        "vessel_count": 2,
        "obstacle_count": 0,
    }
    assert (second["fec_id"], second["case_index"], second["vessel_count"]) == ("explored/00001", 1, 3)
    page = client.get(path, params={"step": "design_space_exploration", "limit": 1, "offset": 1})
    assert [row["fec_id"] for row in page.json()] == ["explored/00001"] and page.headers["x-total-count"] == "2"
    # the rows of the other steps carry no counts
    assert "vessel_count" not in client.get(path, params={"step": "scene_generation"}).json()[0] if client.get(path, params={"step": "scene_generation"}).json() else True


def test_the_exploration_has_no_findings_and_is_refused_for_a_campaign_that_does_not_explore(client, stores):
    campaign_id = create_exploring(client)["campaign_id"]
    findings = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/findings", params={"step": "design_space_exploration"})
    assert findings.status_code == 422 and "has no monitor result summaries" in findings.json()["detail"]
    plain = create(client).json()["campaign_id"]
    refused = client.get(f"{CAMPAIGNS_PATH}/{plain}/outputs", params={"step": "design_space_exploration"})
    assert refused.status_code == 422 and "does not run design_space_exploration" in refused.json()["detail"]


def test_a_case_of_an_explored_fec_names_the_exploration_as_its_source(client, stores):
    campaign_id = create_exploring(client)["campaign_id"]
    exploration, specs = seed_explored(stores, campaign_id)
    source = {"campaign_id": campaign_id, "case_id": exploration.case_id, "step": "design_space_exploration"}
    (case,) = stores.cases.create_cases(campaign_id, [NewCase("explored/00000", 0, 7, input_artifact=specs[0].content_hash, input_source=source)])
    detail = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases/{case.case_id}").json()
    assert (detail["fec_id"], detail["input_artifact"], detail["input_source"]) == ("explored/00000", specs[0].content_hash, source)
    (row,) = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/outputs", params={"step": "scene_generation"}).json()
    assert row["input_source"] == source and "vessel_count" not in row
