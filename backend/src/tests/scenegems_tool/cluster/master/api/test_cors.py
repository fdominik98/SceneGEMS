"""CORS on the operator listener: the web UI's origins may call it from a browser, nobody else."""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from scenegems_tool.cluster.master.api.master_apps import create_master_apps, create_operator_app
from scenegems_tool.cluster.master.api.operator_routes import NODES_PATH, STATUS_PATH
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH, CATALOG_PATH, NODE_CONTROL_PATH

UI = "http://localhost:5173"
UI_BY_ADDRESS = "http://127.0.0.1:5173"
STRANGER = "https://evil.example"


@pytest.fixture
def operator(memory_plane):
    with TestClient(create_operator_app(memory_plane)) as client:
        yield client


def preflight(client, path, origin=UI, method="POST", headers="content-type"):
    request_headers = {"Origin": origin, "Access-Control-Request-Method": method}
    if headers:
        request_headers["Access-Control-Request-Headers"] = headers
    return client.options(path, headers=request_headers)


@pytest.mark.parametrize("origin", [UI, UI_BY_ADDRESS])
def test_the_default_origins_pass_a_preflight_of_a_campaign_create(operator, origin):
    response = preflight(operator, CAMPAIGNS_PATH, origin)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert set(response.headers["access-control-allow-methods"].replace(" ", "").split(",")) == {"GET", "POST", "DELETE", "HEAD"}
    allowed = {name.strip() for name in response.headers["access-control-allow-headers"].lower().split(",")}
    assert "content-type" in allowed and "authorization" not in allowed


def test_a_delete_of_another_origin_is_refused_by_the_origin_guard(operator):
    assert operator.delete(f"{CAMPAIGNS_PATH}/c1", headers={"Origin": STRANGER}).status_code == 403


def test_other_origins_are_refused(operator):
    response = preflight(operator, CAMPAIGNS_PATH, STRANGER)
    assert response.status_code == 400 and "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in operator.get(STATUS_PATH, headers={"Origin": STRANGER}).headers
    assert "access-control-allow-origin" not in operator.get(STATUS_PATH, headers={"Origin": "http://localhost:5174"}).headers  # same host, another port


def test_only_get_post_delete_and_head_and_the_content_type_header_are_allowed(operator):
    assert preflight(operator, f"{CAMPAIGNS_PATH}/c1", method="DELETE").status_code == 200
    for method in ("PUT", "PATCH"):
        assert preflight(operator, CAMPAIGNS_PATH, method=method).status_code == 400, method
    assert preflight(operator, CAMPAIGNS_PATH, headers="authorization").status_code == 400
    for method in ("GET", "HEAD"):
        assert preflight(operator, NODES_PATH, method=method, headers="").status_code == 200, method


def test_a_read_from_an_allowed_origin_exposes_the_total_and_download_headers(operator):
    response = operator.get(f"{CATALOG_PATH}/fecs", headers={"Origin": UI})
    assert response.status_code == 200 and response.headers["access-control-allow-origin"] == UI
    exposed = {name.strip().lower() for name in response.headers["access-control-expose-headers"].split(",")}
    assert exposed == {"x-total-count", "content-disposition"}
    assert "x-total-count" in response.headers  # what the browser may now read


def test_a_request_without_an_origin_gets_no_cors_headers(operator):
    response = operator.get(STATUS_PATH)
    assert response.status_code == 200 and not [name for name in response.headers if name.lower().startswith("access-control")]


def test_the_origins_come_from_the_caller(memory_plane):
    with TestClient(create_operator_app(memory_plane, allowed_origins=["https://ui.lab.example"])) as client:
        assert client.get(STATUS_PATH, headers={"Origin": "https://ui.lab.example"}).headers["access-control-allow-origin"] == "https://ui.lab.example"
        assert "access-control-allow-origin" not in client.get(STATUS_PATH, headers={"Origin": UI}).headers


def test_the_workbench_gateway_behind_the_routes_is_covered_too(memory_plane):
    gateway = FastAPI()

    @gateway.get("/health")
    def health():
        return {"status": "ok"}

    with TestClient(create_operator_app(memory_plane, gateway)) as client:
        assert client.get("/health", headers={"Origin": UI}).headers["access-control-allow-origin"] == UI


def test_the_node_api_has_no_cors(memory_plane):
    apps = create_master_apps(memory_plane)
    with TestClient(apps.node_api) as client:
        response = preflight(client, NODE_CONTROL_PATH)
        assert "access-control-allow-origin" not in response.headers and response.status_code != 200
    with TestClient(apps.operator) as client:
        assert client.get(STATUS_PATH, headers={"Origin": UI}).headers["access-control-allow-origin"] == UI  # create_master_apps passes the default


def test_create_master_apps_hands_the_origins_to_the_operator_app(memory_plane):
    apps = create_master_apps(memory_plane, allowed_origins=("https://ui.lab.example",))
    with TestClient(apps.operator) as client:
        assert client.get(STATUS_PATH, headers={"Origin": "https://ui.lab.example"}).headers["access-control-allow-origin"] == "https://ui.lab.example"
        assert "access-control-allow-origin" not in client.get(STATUS_PATH, headers={"Origin": UI}).headers
