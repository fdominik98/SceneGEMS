from scenegems_tool.cluster.protocol.messages import Welcome
from scenegems_tool.cluster.protocol.routes import WORKER_NODE_CONTROL_PATH
from tests.scenegems_tool.cluster.control_node.api.test_control_node_apps import _paths


def test_a_worker_node_connects_to_the_control_socket_and_gets_its_welcome(client, make_worker_node):
    worker_node = make_worker_node("lab 1")
    assert isinstance(worker_node.connect(), Welcome)


def test_the_worker_node_api_serves_the_control_socket_and_nothing_to_pair_with(client):
    assert WORKER_NODE_CONTROL_PATH in _paths(client.app)
    for path in ("/cluster/ca-certificate", "/cluster/pairing"):
        assert client.get(path).status_code == 404 and client.post(path, content="{}").status_code == 404
