from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_control_node_apps, create_operator_app
from scenegems_tool.cluster.control_node.api.operator_routes import STATUS_PATH
from scenegems_tool.cluster.protocol.routes import JOBS_PATH, WORKER_NODE_CONTROL_PATH


def _stub_gateway(events):
    @asynccontextmanager
    async def lifespan(_app):
        events.append("gateway up")
        yield
        events.append("gateway down")

    gateway = FastAPI(lifespan=lifespan)

    @gateway.get("/health")
    def health():
        return {"status": "ok"}

    @gateway.get(STATUS_PATH)
    def shadowed():
        return {"from": "gateway"}

    @gateway.websocket("/ws/scenegems_backend_service")
    async def socket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hello from the workbench")
        await websocket.close()

    return gateway


def _paths(app: FastAPI):
    return {getattr(route, "path", None) for route in app.routes}


def test_each_listener_serves_only_its_routes(plane):
    apps = create_control_node_apps(plane)
    assert WORKER_NODE_CONTROL_PATH in _paths(apps.worker_node_api)
    assert not {JOBS_PATH, "/ws/scenegems_backend_service"} & _paths(apps.worker_node_api)
    assert JOBS_PATH in _paths(apps.operator) and WORKER_NODE_CONTROL_PATH not in _paths(apps.operator)
    assert set(vars(apps)) == {"worker_node_api", "operator"}  # no pairing, no broker login hook


def test_the_gateway_is_mounted_behind_the_operator_routes_with_its_lifespan(plane):
    events = []
    with TestClient(create_operator_app(plane, _stub_gateway(events))) as client:
        assert events == ["gateway up"]
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get(STATUS_PATH).json()["control_node_id"] == "lab-control-node"  # the cluster route wins
        with client.websocket_connect("/ws/scenegems_backend_service") as socket:
            assert socket.receive_text() == "hello from the workbench"
    assert events == ["gateway up", "gateway down"]


def test_the_real_workbench_gateway_mounts_unchanged(plane):
    from scenegems_tool.gateway.websocket_app import app as gateway

    operator = create_operator_app(plane, gateway)
    client = TestClient(operator)  # no lifespan: the gateway's would install signal handlers and stop Docker containers at exit
    assert client.get("/health").json() == {"status": "ok"}
    mounted = next(route for route in operator.routes if getattr(route, "app", None) is gateway)
    assert "/ws/scenegems_backend_service" in _paths(mounted.app)
