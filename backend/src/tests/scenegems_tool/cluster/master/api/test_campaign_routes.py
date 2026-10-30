"""The operator's campaign routes on a real Postgres (-m postgres), through a test client."""

import csv
import io
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH, JOBS_PATH
from scenegems_tool.persistence.schema import CampaignActualState, CaseState, MonitorImplementation, PipelineStage, TrajectoryGeneratorImplementation, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NewCase, NewRunRecord, NewVerdict, NodeStore
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock

pytestmark = pytest.mark.postgres

EXIT_CAMPAIGN = Path(__file__).resolve().parents[3] / "assurance" / "campaign" / "data" / "exit_campaign.yaml"
CLASS_A = "2vessel_0obstacle_scenarios/functional_model0"
CLASS_B = "2vessel_0obstacle_scenarios/functional_model1"
JSON = {"Content-Type": "application/json"}
YAML = {"Content-Type": "application/yaml"}


def small_config(**changes) -> str:
    """The exit campaign cut down to two classes."""
    config = yaml.safe_load(EXIT_CAMPAIGN.read_text(encoding="utf-8"))
    config["scope"] = [{"classes": [CLASS_A, CLASS_B], "quota": 2, "failure_budget": 1}]
    config.update(changes)
    return yaml.safe_dump(config)


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


@pytest.fixture
def plane(session_factory, clock) -> ControlPlane:
    nodes = NodeStore(session_factory, clock)
    return ControlPlane("lab-master", nodes, JobStore(session_factory, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def client(plane, stores):
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        yield client


def create(client, text=None, **query):
    return client.post(CAMPAIGNS_PATH, content=small_config() if text is None else text, headers=YAML, params=query)


def seed_cases(stores, campaign_id):
    """Class A: case 0 complete with a passed verdict, case 1 complete with a failed one. Class B: case 0 active, in flight."""
    a0, a1 = stores.cases.create_cases(campaign_id, [NewCase(CLASS_A, 0, 100), NewCase(CLASS_A, 1, 101)])
    (b0,) = stores.cases.create_cases(campaign_id, [NewCase(CLASS_B, 0, 200)])
    for case, verdict, rules, sensitive in ((a0, VerdictState.PASSED, (), False), (a1, VerdictState.FAILED, ("rule_15",), True)):
        record = stores.results.add_run_record(NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT, True, {"mode": "usv_navigation"}, {}, case.seed, steps=10))
        stores.results.add_verdict(
            NewVerdict(
                case.case_id, 0, verdict, MonitorImplementation.POST_HOC, failed_rules=rules, first_failure_time_s=4.5 if rules else None, sensitive=sensitive, run_record_id=record.run_record_id
            )
        )
        stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    return a0, a1, b0


def test_creating_a_campaign_from_yaml_pins_the_expected_fingerprints_and_waits_paused(client, stores):
    response = create(client)
    assert response.status_code == 201
    view = response.json()
    assert view["desired_state"] == "paused" and view["actual_state"] == "created" and view["config_version"] == 1
    assert view["pinned_fingerprints"] == EXPECTED
    assert view["name"] == "phase 4 exit campaign"
    assert [entry["fec_id"] for entry in view["fecs"]] == [CLASS_A, CLASS_B]
    assert view["totals"]["quota"] == 4 and view["totals"]["fecs_open"] == 2
    stored = stores.campaigns.get_campaign(view["campaign_id"])
    assert stored is not None and stores.campaigns.config_version(view["campaign_id"]).config["scope"][0]["quota"] == 2


def test_creating_with_a_name_and_start_from_yaml(client):
    view = create(client, name="smoke", start="true").json()
    assert view["name"] == "smoke" and view["desired_state"] == "running"


def test_creating_from_a_json_body(client):
    config = yaml.safe_load(small_config())
    response = client.post(CAMPAIGNS_PATH, json={"config": config, "name": "as json", "start": True})
    assert response.status_code == 201
    assert (response.json()["name"], response.json()["desired_state"]) == ("as json", "running")
    as_text = client.post(CAMPAIGNS_PATH, json={"config": small_config()})
    assert as_text.status_code == 201 and as_text.json()["desired_state"] == "paused"


def test_creating_the_full_exit_campaign(client):
    view = create(client, EXIT_CAMPAIGN.read_text(encoding="utf-8")).json()
    assert view["totals"]["fecs"] == 70 and view["totals"]["quota"] == 1050


def test_a_master_without_a_listing_stores_no_fingerprints(session_factory, clock, stores):
    pending = ExpectedFingerprints(lambda: {})
    plane = ControlPlane("lab-master", NodeStore(session_factory, clock), JobStore(session_factory, clock), pending, clock=clock)
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        assert create(client).json()["pinned_fingerprints"] == {}


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("scope: [", "not valid YAML"),
        ("- a list", "mapping"),
        ("name: nothing\n", "scope"),
        (small_config(unknown_section={"a": 1}), "unknown_section"),
    ],
)
def test_a_config_that_does_not_load_answers_422_with_the_reasons(client, stores, text, fragment):
    response = create(client, text)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reasons"] and fragment in " ".join(detail["reasons"])
    assert stores.campaigns.list_campaigns() == []


def test_a_config_the_catalog_refuses_answers_422_with_every_reason(client):
    config = yaml.safe_load(small_config())
    config["scope"] = [{"classes": ["9vessel_9obstacle_scenarios/functional_model0"], "quota": 1}, {"patterns": ["8vessel_*_scenarios"], "quota": 1}]
    response = create(client, yaml.safe_dump(config))
    reasons = response.json()["detail"]["reasons"]
    assert response.status_code == 422 and len(reasons) == 2
    assert "no FEC" in reasons[0] and "matches no FEC" in reasons[1]


def test_a_config_the_resolver_refuses_answers_422(client):
    config = yaml.safe_load(small_config())
    config["execution"]["runs"][0]["stack"] = {"simulation_layer": "ardupilot_sim", "mode": "replay", "speedup": 1000}  # a pace the resolver measured as too fast
    response = create(client, yaml.safe_dump(config))
    assert response.status_code == 422 and "speedup 1000 exceeds the measured max_speedup" in response.json()["detail"]["reasons"][0]
    config["execution"]["runs"][0]["stack"] = {"simulation_layer": "gazebo", "mode": "replay"}
    assert create(client, yaml.safe_dump(config)).status_code == 201, "a Gazebo replay is a valid stack since P6.6"


def test_a_body_in_another_format_is_refused(client):
    assert client.post(CAMPAIGNS_PATH, content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(CAMPAIGNS_PATH, content="{", headers=JSON).status_code == 422
    assert client.post(CAMPAIGNS_PATH, json={"no_config": 1}).status_code == 422
    assert client.post(CAMPAIGNS_PATH, json={"config": {}, "extra": 1}).status_code == 422
    assert client.post(CAMPAIGNS_PATH, json={"config": small_config(), "start": "yes"}).status_code == 422
    assert client.post(CAMPAIGNS_PATH, json={"config": small_config(), "name": " "}).status_code == 422


def test_listing_campaigns_filters_by_state_and_pages(client, stores):
    first = create(client, name="first").json()["campaign_id"]
    second = create(client, name="second").json()["campaign_id"]
    stores.campaigns.set_actual_state(first, CampaignActualState.RUNNING)
    listed = client.get(CAMPAIGNS_PATH).json()
    assert {entry["campaign_id"] for entry in listed} == {first, second}
    assert [entry["campaign_id"] for entry in client.get(CAMPAIGNS_PATH, params={"state": "running"}).json()] == [first]
    assert len(client.get(CAMPAIGNS_PATH, params={"state": ["running", "created"]}).json()) == 2
    assert len(client.get(CAMPAIGNS_PATH, params={"limit": 1}).json()) == 1
    assert len(client.get(CAMPAIGNS_PATH, params={"limit": 1, "offset": 1}).json()) == 1
    assert client.get(CAMPAIGNS_PATH, params={"state": "bogus"}).status_code == 422


def test_showing_a_campaign_gives_coverage_per_class(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    view = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}").json()
    by_class = {entry["fec_id"]: entry for entry in view["fecs"]}
    assert by_class[CLASS_A]["complete"] == 2 and by_class[CLASS_A]["verdicts"] == {"0": {"passed": 1, "failed": 1}}
    assert by_class[CLASS_B]["in_flight"] == 1 and by_class[CLASS_B]["verdicts"] == {} and by_class[CLASS_B]["state"] == "open"
    assert by_class[CLASS_A]["failure_budget_left"] == 1
    assert view["totals"]["verdicts"] == {"passed": 1, "failed": 1} and view["totals"]["complete"] == 2
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/fecs").json() == view["fecs"]


def test_an_unlimited_failure_budget_is_null_in_the_views(client):
    config = small_config(scope=[{"classes": [CLASS_A], "quota": 2, "failure_budget": "unlimited"}])
    validated = client.post(f"{CAMPAIGNS_PATH}/validate", content=config, headers=YAML).json()
    assert [(entry["fec_id"], entry["failure_budget"]) for entry in validated["fecs"]] == [(CLASS_A, None)]
    campaign_id = create(client, config).json()["campaign_id"]
    (entry,) = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/fecs").json()
    assert (entry["quota"], entry["failure_budget"], entry["failure_budget_left"]) == (2, None, None)
    (version,) = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/config").json()["versions"]
    assert version["config"]["scope"][0]["failure_budget"] == "unlimited"


def test_unknown_campaigns_answer_404_on_every_route(client):
    for suffix in ("", "/fecs", "/cases", "/cases/1", "/verdicts", "/run-records", "/events", "/config"):
        assert client.get(f"{CAMPAIGNS_PATH}/no-such{suffix}").status_code == 404, suffix
    assert client.post(f"{CAMPAIGNS_PATH}/no-such/pause").status_code == 404


def test_cases_are_filtered_and_paged(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    cases = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases").json()
    assert [(case["fec_id"], case["case_index"]) for case in cases] == [(CLASS_A, 0), (CLASS_A, 1), (CLASS_B, 0)]
    assert cases[0]["state"] == "complete" and cases[0]["stage"] == "verdict" and cases[0]["seed"] == 100
    assert [case["case_index"] for case in client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases", params={"fec_id": CLASS_B}).json()] == [0]
    assert len(client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases", params={"state": "active"}).json()) == 1
    assert len(client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases", params={"stage": "generate_scene"}).json()) == 1
    assert len(client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases", params={"limit": 2, "offset": 1}).json()) == 2
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases", params={"stage": "bogus"}).status_code == 422


def test_a_case_shows_its_jobs_run_records_and_verdicts(client, stores, plane):
    campaign_id = create(client).json()["campaign_id"]
    a0, a1, b0 = seed_cases(stores, campaign_id)
    job = client.post(JOBS_PATH, json={"job_type": JobType.SCENE_GENERATION.value, "payload": valid_payload(JobType.SCENE_GENERATION, seed=1)}).json()
    stores.pipeline.add_intent(campaign_id, a1.case_id, PipelineStage.GENERATE_SCENE, "key-scene", None, None, {"job_type": "scene_generation"})
    stores.pipeline.link_job("key-scene", job["job_id"])
    stores.pipeline.add_intent(campaign_id, a1.case_id, PipelineStage.SIMULATE, "key-sim", 0, 0, {"job_type": "simulation"})
    detail = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases/{a1.case_id}").json()
    assert detail["case_id"] == a1.case_id and detail["state"] == "complete"
    assert detail["input_artifact"] is None and detail["input_source"] is None  # a catalog class
    scene, simulate = detail["jobs"]
    assert scene["stage"] == "generate_scene" and scene["job_id"] == job["job_id"] and scene["intent"] is False
    assert scene["job"]["state"] == "queued" and scene["job"]["job_type"] == "scene_generation" and "payload" not in scene["job"]
    assert simulate["intent"] is True and simulate["job"] is None and simulate["run_index"] == 0
    (record,) = detail["run_records"]
    assert record["steps"] == 10 and record["stack"] == {"mode": "usv_navigation"} and record["trajectory_generator"] == "monitor_driven_rrt"
    (verdict,) = detail["verdicts"]
    assert verdict["state"] == "failed" and verdict["failed_rules"] == ["rule_15"] and verdict["first_failure_time_s"] == 4.5 and verdict["sensitive"] is True
    other = create(client).json()["campaign_id"]
    assert client.get(f"{CAMPAIGNS_PATH}/{other}/cases/{a1.case_id}").status_code == 404
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases/999999").status_code == 404


def test_verdicts_are_filtered_and_paged(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts"
    assert [verdict["state"] for verdict in client.get(path).json()] == ["passed", "failed"]
    assert [verdict["state"] for verdict in client.get(path, params={"state": "failed"}).json()] == ["failed"]
    assert [verdict["sensitive"] for verdict in client.get(path, params={"sensitive": "true"}).json()] == [True]
    assert client.get(path, params={"fec_id": CLASS_B}).json() == []
    assert len(client.get(path, params={"fec_id": CLASS_A, "run_index": 0}).json()) == 2
    assert client.get(path, params={"run_index": 1}).json() == []
    assert len(client.get(path, params={"limit": 1, "offset": 1}).json()) == 1
    assert client.get(path, params={"format": "xml"}).status_code == 422


def test_verdicts_stream_as_csv(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    response = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv"})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="verdicts-{campaign_id}.csv"'
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [row["state"] for row in rows] == ["passed", "failed"]
    failed = rows[1]
    assert failed["fec_id"] == CLASS_A and failed["failed_rules"] == "rule_15" and failed["first_failure_time_s"] == "4.5" and failed["sensitive"] == "True"
    assert rows[0]["first_failure_time_s"] == "" and rows[0]["margin"] == "" and rows[0]["failed_rules"] == ""
    filtered = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv", "state": "failed"})
    assert len(list(csv.DictReader(io.StringIO(filtered.text)))) == 1
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv", "fec_id": CLASS_B}).text.count("\n") == 1  # the header alone


def test_the_csv_pages_through_every_verdict(client, stores, monkeypatch):
    from scenegems_tool.cluster.master.api import campaign_routes

    monkeypatch.setattr(campaign_routes, "CSV_PAGE", 1)
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    response = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv"})
    assert [row["state"] for row in csv.DictReader(io.StringIO(response.text))] == ["passed", "failed"]
    limited = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv", "limit": 1, "offset": 1})
    assert [row["state"] for row in csv.DictReader(io.StringIO(limited.text))] == ["failed"]


def test_run_records_are_filtered(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/run-records"
    assert len(client.get(path).json()) == 2
    assert client.get(path, params={"fec_id": CLASS_B}).json() == []
    assert client.get(path, params={"run_index": 3}).json() == []
    assert len(client.get(path, params={"limit": 1}).json()) == 1


def test_events_come_after_an_event_id(client):
    campaign_id = create(client).json()["campaign_id"]
    client.post(f"{CAMPAIGNS_PATH}/{campaign_id}/start")
    client.post(f"{CAMPAIGNS_PATH}/{campaign_id}/pause")
    events = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/events").json()
    assert [event["kind"] for event in events] == ["created", "desired_state_changed", "desired_state_changed"]
    assert events[1]["detail"] == {"from": "paused", "to": "running"}
    assert events[0]["at"].startswith("2026-10-25T12:00:00")
    later = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/events", params={"after": events[0]["event_id"]}).json()
    assert [event["event_id"] for event in later] == [events[1]["event_id"], events[2]["event_id"]]
    assert len(client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/events", params={"limit": 1}).json()) == 1
    assert client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/events", params={"after": events[2]["event_id"]}).json() == []


def test_the_config_route_gives_the_versions(client):
    campaign_id = create(client).json()["campaign_id"]
    config = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/config").json()
    assert config["current_version"] == 1 and [version["version"] for version in config["versions"]] == [1]
    version = config["versions"][0]
    assert len(version["config_hash"]) == 64 and version["config"]["policy"]["seed"] == 20261025


def test_the_controls_set_the_desired_state(client):
    campaign_id = create(client).json()["campaign_id"]
    base = f"{CAMPAIGNS_PATH}/{campaign_id}"
    for control, desired in (("start", "running"), ("pause", "paused"), ("resume", "running"), ("drain", "draining"), ("start", "running")):
        response = client.post(f"{base}/{control}")
        assert response.status_code == 200 and response.json()["desired_state"] == desired, control
    assert client.post(f"{base}/start").json()["desired_state"] == "running"  # again: nothing changes
    assert client.get(base).json()["desired_state"] == "running"
    assert client.post(f"{base}/launch").status_code == 404


def test_a_stopped_campaign_refuses_every_other_control(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    base = f"{CAMPAIGNS_PATH}/{campaign_id}"
    assert client.post(f"{base}/stop").json()["desired_state"] == "stopped"
    assert client.post(f"{base}/stop").status_code == 200  # stopping twice is fine
    for control in ("start", "pause", "drain", "resume"):
        response = client.post(f"{base}/{control}")
        assert response.status_code == 409 and "stop" in response.json()["detail"], control
    assert client.get(base).json()["desired_state"] == "stopped"


def test_a_finished_campaign_refuses_controls(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    stores.campaigns.set_actual_state(campaign_id, CampaignActualState.COMPLETED)
    assert client.post(f"{CAMPAIGNS_PATH}/{campaign_id}/start").status_code == 409


def test_the_job_view_has_available_at(client):
    job = client.post(JOBS_PATH, json={"job_type": JobType.SCENE_GENERATION.value, "payload": valid_payload(JobType.SCENE_GENERATION, seed=1)}).json()
    assert job["available_at"].startswith("2026-10-25T12:00:00")


def test_without_the_campaign_stores_the_routes_answer_503():
    clock = ManualClock()
    nodes = InMemoryNodeStore(clock)
    plane = ControlPlane("lab-master", nodes, InMemoryJobStore(nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
    with TestClient(create_operator_app(plane)) as client:
        for response in (
            client.get(CAMPAIGNS_PATH),
            client.post(CAMPAIGNS_PATH, content="x", headers=YAML),
            client.post(f"{CAMPAIGNS_PATH}/validate", content="x", headers=YAML),
            client.get(f"{CAMPAIGNS_PATH}/abc/cases"),
            client.post(f"{CAMPAIGNS_PATH}/abc/stop"),
        ):
            assert response.status_code == 503 and "campaign stores" in response.json()["detail"]
        assert client.get(JOBS_PATH).status_code == 200


# Validate


def test_validating_a_config_creates_nothing_and_describes_what_a_campaign_would_run(client, stores):
    response = client.post(f"{CAMPAIGNS_PATH}/validate", content=small_config(), headers=YAML)
    assert response.status_code == 200
    view = response.json()
    assert view["valid"] is True and view["name"] == "phase 4 exit campaign"
    assert len(view["config_hash"]) == 64
    assert [(entry["fec_id"], entry["quota"], entry["failure_budget"]) for entry in view["fecs"]] == [(CLASS_A, 2, 1), (CLASS_B, 2, 1)]
    assert all(len(entry["content_hash"]) == 64 and entry["vessel_count"] == 2 and entry["obstacle_count"] == 0 for entry in view["fecs"])
    assert view["cases_planned"] == 4
    assert [(run["run_index"], run["repeatability_tier"], run["warnings"]) for run in view["runs"]] == [(0, "exact", [])]
    assert stores.campaigns.list_campaigns() == []
    assert client.get(CAMPAIGNS_PATH).headers["x-total-count"] == "0"


def test_the_hash_of_a_validated_config_is_the_one_the_campaign_gets(client):
    validated = client.post(f"{CAMPAIGNS_PATH}/validate", content=small_config(), headers=YAML).json()
    created = create(client).json()
    version = client.get(f"{CAMPAIGNS_PATH}/{created['campaign_id']}/config").json()["versions"][0]
    assert version["config_hash"] == validated["config_hash"]
    assert created["totals"]["quota"] == validated["cases_planned"]


def test_validating_takes_the_bodies_create_takes(client):
    config = yaml.safe_load(small_config())
    as_object = client.post(f"{CAMPAIGNS_PATH}/validate", json={"config": config, "name": "x", "start": True})
    as_text = client.post(f"{CAMPAIGNS_PATH}/validate", json={"config": small_config()})
    as_yaml = client.post(f"{CAMPAIGNS_PATH}/validate", content=small_config(), headers=YAML, params={"name": "x", "start": "true"})
    assert [response.status_code for response in (as_object, as_text, as_yaml)] == [200, 200, 200]
    assert as_object.json()["config_hash"] == as_text.json()["config_hash"] == as_yaml.json()["config_hash"]
    assert client.post(f"{CAMPAIGNS_PATH}/validate", content="x", headers={"Content-Type": "text/plain"}).status_code == 415
    assert client.post(f"{CAMPAIGNS_PATH}/validate", json={"no_config": 1}).status_code == 422


@pytest.mark.parametrize("text", ["scope: [", "- a list", "name: nothing\n", small_config(unknown_section={"a": 1})])
def test_validating_answers_the_422_create_answers(client, text):
    validated = client.post(f"{CAMPAIGNS_PATH}/validate", content=text, headers=YAML)
    created = create(client, text)
    assert validated.status_code == created.status_code == 422
    assert validated.json() == created.json()


def test_validating_reports_every_reason_of_the_catalog_and_the_resolver(client):
    config = yaml.safe_load(small_config())
    config["scope"] = [{"classes": ["9vessel_9obstacle_scenarios/functional_model0"], "quota": 1}, {"patterns": ["8vessel_*_scenarios"], "quota": 1}]
    config["execution"]["runs"][0]["stack"] = {"simulation_layer": "gazebo", "mode": "replay"}
    text = yaml.safe_dump(config)
    validated = client.post(f"{CAMPAIGNS_PATH}/validate", content=text, headers=YAML)
    assert validated.status_code == 422 and len(validated.json()["detail"]["reasons"]) >= 2
    assert validated.json() == create(client, text).json()


# Totals


def total(response) -> int:
    return int(response.headers["x-total-count"])


def test_campaigns_have_their_filtered_total(client, stores):
    first = create(client, name="first").json()["campaign_id"]
    create(client, name="second")
    stores.campaigns.set_actual_state(first, CampaignActualState.RUNNING)
    assert total(client.get(CAMPAIGNS_PATH)) == 2
    assert total(client.get(CAMPAIGNS_PATH, params={"limit": 1, "offset": 1})) == 2  # the page does not narrow it
    running = client.get(CAMPAIGNS_PATH, params={"state": "running"})
    assert total(running) == len(running.json()) == 1
    assert total(client.get(CAMPAIGNS_PATH, params={"state": ["running", "created"]})) == 2
    assert total(client.get(CAMPAIGNS_PATH, params={"state": "completed"})) == 0


def test_cases_have_their_filtered_total(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/cases"
    assert total(client.get(path)) == 3
    assert total(client.get(path, params={"limit": 1})) == 3
    assert total(client.get(path, params={"fec_id": CLASS_A})) == 2
    assert total(client.get(path, params={"state": "active"})) == 1
    assert total(client.get(path, params={"state": ["active", "complete"], "fec_id": CLASS_B})) == 1
    assert total(client.get(path, params={"stage": "generate_scene"})) == 1
    assert total(client.get(path, params={"stage": ["verdict", "generate_scene"]})) == 3
    assert total(client.get(path, params={"stage": "monitor"})) == 0


def test_verdicts_have_their_filtered_total(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts"
    assert total(client.get(path)) == 2
    assert total(client.get(path, params={"limit": 1, "offset": 1})) == 2
    assert total(client.get(path, params={"state": "failed"})) == 1
    assert total(client.get(path, params={"sensitive": "false"})) == 1
    assert total(client.get(path, params={"fec_id": CLASS_B})) == 0
    assert total(client.get(path, params={"run_index": 0, "fec_id": CLASS_A})) == 2
    assert total(client.get(path, params={"run_index": 1})) == 0
    csv_response = client.get(path, params={"format": "csv", "state": "failed"})
    assert total(csv_response) == 1 and csv_response.headers["content-disposition"].startswith("attachment")


def test_run_records_have_their_filtered_total(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    seed_cases(stores, campaign_id)
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/run-records"
    assert total(client.get(path)) == 2
    assert total(client.get(path, params={"limit": 1})) == 2
    assert total(client.get(path, params={"fec_id": CLASS_B})) == 0
    assert total(client.get(path, params={"run_index": 3})) == 0


def test_events_have_their_total_after_the_event_id(client):
    campaign_id = create(client).json()["campaign_id"]
    client.post(f"{CAMPAIGNS_PATH}/{campaign_id}/start")
    client.post(f"{CAMPAIGNS_PATH}/{campaign_id}/pause")
    path = f"{CAMPAIGNS_PATH}/{campaign_id}/events"
    events = client.get(path).json()
    assert total(client.get(path)) == 3
    assert total(client.get(path, params={"limit": 1})) == 3
    assert total(client.get(path, params={"after": events[0]["event_id"]})) == 2
    assert total(client.get(path, params={"after": events[2]["event_id"]})) == 0


# Case index


def test_verdicts_and_run_records_carry_the_index_of_their_case(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    a0, a1, _ = seed_cases(stores, campaign_id)
    verdicts = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts").json()
    assert [(verdict["case_id"], verdict["case_index"]) for verdict in verdicts] == [(a0.case_id, 0), (a1.case_id, 1)]
    records = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/run-records").json()
    assert [(record["case_id"], record["case_index"]) for record in records] == [(a0.case_id, 0), (a1.case_id, 1)]
    detail = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/cases/{a1.case_id}").json()
    assert detail["verdicts"][0]["case_index"] == 1 and detail["run_records"][0]["case_index"] == 1 and detail["case_index"] == 1


def test_the_csv_has_the_case_index_beside_the_case_id(client, stores):
    campaign_id = create(client).json()["campaign_id"]
    a0, a1, _ = seed_cases(stores, campaign_id)
    response = client.get(f"{CAMPAIGNS_PATH}/{campaign_id}/verdicts", params={"format": "csv"})
    header = response.text.splitlines()[0].split(",")
    assert header[header.index("case_id") + 1] == "case_index"
    assert [(row["case_id"], row["case_index"]) for row in csv.DictReader(io.StringIO(response.text))] == [(str(a0.case_id), "0"), (str(a1.case_id), "1")]
