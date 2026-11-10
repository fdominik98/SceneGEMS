from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, JOBS_PATH, WORKER_NODE_CONTROL_PATH, WORKER_NODE_ID_HEADER


def test_paths_are_distinct_and_under_cluster():
    paths = [WORKER_NODE_CONTROL_PATH, JOBS_PATH, ARTIFACTS_PATH]
    assert len(set(paths)) == len(paths)
    assert all(path.startswith("/cluster/") for path in paths)


def test_the_worker_node_names_itself_in_a_plain_header():
    assert WORKER_NODE_ID_HEADER == "X-Worker-Node-Id"  # the artifact routes' only identification: control node and worker nodes trust the VPN
