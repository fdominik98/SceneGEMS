"""The setting routes: the cluster's domain configuration and the campaign presets.

Without the campaign stores (no database) the master serves the defaults and the shipped presets read-only; the
saving routes run on a real Postgres (-m postgres).
"""

import pytest
import yaml
from starlette.testclient import TestClient

from scenegems_tool.assurance.campaign.campaign_presets import NO_INPUT_REASON, builtin_presets
from scenegems_tool.assurance.campaign.domain_presets import default_domain
from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.routes import CAMPAIGN_PRESETS_PATH, CAMPAIGNS_PATH, DOMAIN_PATH
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NodeStore
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.persistence.stores.builders import ManualClock

DOMAIN = {"colregs_constants": "SAFE_DISTANCE: 400\r\n", "vessel_types": "Ferry:\n  max_speed: 12\n", "obstacle_types": "Buoy:\n  radius: 2\n"}
PRESET_CONFIG = {"format": 2, "name": "nightly sitl", "steps": ["simulation"], "execution": {"runs": [{"stack": {"simulation_layer": "ardupilot_sim", "speedup": 10}}]}}


@pytest.fixture
def read_only(memory_plane):
    with TestClient(create_operator_app(memory_plane)) as client:
        yield client


# Without the campaign stores


def test_without_stores_the_domain_is_the_default_presets(read_only):
    response = read_only.get(DOMAIN_PATH)
    assert response.status_code == 200
    assert response.json() == {**default_domain(), "saved": False, "updated_at": None, "editable": False}


def test_without_stores_nothing_is_saved(read_only):
    assert read_only.post(DOMAIN_PATH, json=DOMAIN).status_code == 503
    assert read_only.post(CAMPAIGN_PRESETS_PATH, json={"name": "mine", "config": PRESET_CONFIG}).status_code == 503


def test_the_shipped_presets_are_listed_in_file_order(read_only):
    response = read_only.get(CAMPAIGN_PRESETS_PATH)
    assert response.status_code == 200
    listed = response.json()
    assert [preset["preset_id"] for preset in listed] == [preset.preset_id for preset in builtin_presets()]
    first = listed[0]
    assert first["builtin"] and first["name"] == first["config"]["name"] and first["description"]
    assert first["steps"] == ["scene_generation", "trajectory_generation", "simulation"]
    assert first["created_at"] is None and first["updated_at"] is None


def test_a_shipped_preset_cannot_be_deleted(read_only):
    assert read_only.delete(f"{CAMPAIGN_PRESETS_PATH}/{builtin_presets()[0].preset_id}").status_code == 409


# With the campaign stores


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


@pytest.fixture
def client(session_factory, clock, stores):
    plane = ControlPlane("lab-master", NodeStore(session_factory, clock), JobStore(session_factory, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        yield client


@pytest.mark.postgres
def test_the_saved_domain_is_the_clusters(client, clock):
    assert client.get(DOMAIN_PATH).json()["saved"] is False
    response = client.post(DOMAIN_PATH, json=DOMAIN)
    assert response.status_code == 200
    saved = response.json()
    assert saved["colregs_constants"] == "SAFE_DISTANCE: 400\n"  # LF line endings, as campaign configs hold them
    assert saved["saved"] and saved["editable"] and saved["updated_at"] == clock().isoformat()
    assert client.get(DOMAIN_PATH).json() == saved


@pytest.mark.postgres
@pytest.mark.parametrize(
    "body, reason",
    [
        ({**DOMAIN, "vessel_types": "just text"}, "vessel_types: Value error, expected a YAML mapping"),
        ({**DOMAIN, "obstacle_types": "a: [\n"}, "obstacle_types: Value error, not valid YAML"),
        ({key: value for key, value in DOMAIN.items() if key != "colregs_constants"}, "colregs_constants: a text is required"),
        ({**DOMAIN, "wind": "calm"}, "unknown fields in the body: ['wind']"),
        (["not", "an", "object"], "the body is an object"),
    ],
)
def test_a_domain_that_is_not_valid_is_refused(client, body, reason):
    response = client.post(DOMAIN_PATH, json=body)
    assert response.status_code == 422
    assert any(reason in item for item in response.json()["detail"]["reasons"])
    assert client.get(DOMAIN_PATH).json()["saved"] is False


@pytest.mark.postgres
def test_a_campaign_without_domain_content_gets_the_clusters(client):
    client.post(DOMAIN_PATH, json=DOMAIN)
    config = {"format": 2, "name": "lab", "steps": ["scene_generation"], "scope": [{"classes": ["2vessel_0obstacle_scenarios/functional_model0"], "quota": 1}]}
    config["domain"] = {"vessel_types": "Tug:\n  max_speed: 6\n"}
    response = client.post(CAMPAIGNS_PATH, json={"config": config})
    assert response.status_code == 201, response.text
    (version,) = client.get(f"{CAMPAIGNS_PATH}/{response.json()['campaign_id']}/config").json()["versions"]
    stored = version["config"]["domain"]
    assert stored["colregs_constants"] == "SAFE_DISTANCE: 400\n" and stored["obstacle_types"] == DOMAIN["obstacle_types"]
    assert stored["vessel_types"] == "Tug:\n  max_speed: 6\n"  # the config's own content wins
    assert client.post(f"{CAMPAIGNS_PATH}/validate", json={"config": {**config, "domain": {}}}).status_code == 200


@pytest.mark.postgres
def test_a_saved_preset_is_listed_after_the_shipped_ones(client, clock):
    response = client.post(CAMPAIGN_PRESETS_PATH, json={"name": " nightly ", "description": "SITL every night", "config": yaml.safe_dump(PRESET_CONFIG)})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert (saved["name"], saved["description"], saved["builtin"], saved["steps"]) == ("nightly", "SITL every night", False, ["simulation"])
    assert saved["config"] == PRESET_CONFIG and saved["created_at"] == clock().isoformat()
    listed = client.get(CAMPAIGN_PRESETS_PATH).json()
    assert listed[-1] == saved and len(listed) == len(builtin_presets()) + 1


@pytest.mark.postgres
def test_a_taken_preset_name_needs_replace(client):
    first = client.post(CAMPAIGN_PRESETS_PATH, json={"name": "nightly", "config": PRESET_CONFIG}).json()
    assert client.post(CAMPAIGN_PRESETS_PATH, json={"name": "nightly", "config": PRESET_CONFIG}).status_code == 409
    replaced = client.post(CAMPAIGN_PRESETS_PATH, json={"name": "nightly", "config": {**PRESET_CONFIG, "name": "renamed"}, "replace": True})
    assert replaced.status_code == 200 and replaced.json()["preset_id"] == first["preset_id"]
    assert replaced.json()["config"]["name"] == "renamed"
    shipped = builtin_presets()[0].name
    assert client.post(CAMPAIGN_PRESETS_PATH, json={"name": shipped, "config": PRESET_CONFIG, "replace": True}).status_code == 409


@pytest.mark.postgres
@pytest.mark.parametrize(
    "body, reason",
    [
        ({"name": "with input", "config": {**PRESET_CONFIG, "input": {"items": []}}}, NO_INPUT_REASON),
        ({"name": "", "config": PRESET_CONFIG}, '"name" is a text of 1 to 200 characters'),
        ({"name": "bad steps", "config": {**PRESET_CONFIG, "steps": ["planning"]}}, "steps.0"),
        ({"name": "no config"}, 'the body is an object with "name", "config"'),
        ({"name": "colour", "config": PRESET_CONFIG, "colour": "blue"}, "unknown fields in the body: ['colour']"),
    ],
)
def test_a_preset_that_is_not_valid_is_refused(client, body, reason):
    response = client.post(CAMPAIGN_PRESETS_PATH, json=body)
    assert response.status_code == 422
    assert any(reason in item for item in response.json()["detail"]["reasons"])


@pytest.mark.postgres
def test_a_saved_preset_is_deleted(client):
    saved = client.post(CAMPAIGN_PRESETS_PATH, json={"name": "nightly", "config": PRESET_CONFIG}).json()
    assert client.delete(f"{CAMPAIGN_PRESETS_PATH}/{saved['preset_id']}").status_code == 204
    assert client.delete(f"{CAMPAIGN_PRESETS_PATH}/{saved['preset_id']}").status_code == 404
    assert all(preset["builtin"] for preset in client.get(CAMPAIGN_PRESETS_PATH).json())
