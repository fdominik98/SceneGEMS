import pytest

from scenegems_tool.cluster.scope_names import WORKER_NODE_NAME_MAX, is_scope_name, is_worker_node_name


@pytest.mark.parametrize("value", ["", "-a", "a-", "A", "a_b", "a.b", "a/b", "+", "#", "$SYS", "a" * 64, None, 3])
def test_invalid_scope_names(value):
    assert not is_scope_name(value)


def test_a_worker_node_name_is_a_scope_name_of_at_most_28_characters():
    """The names of its objects in the cluster start with it: worker-node-<name> and <name>-design-space-exploration-subsystem fit in 63."""
    assert WORKER_NODE_NAME_MAX == 28 == 63 - 1 - len("design-space-exploration-subsystem")
    assert is_worker_node_name("w" * 28) and is_worker_node_name("lab-pc-3") and is_worker_node_name("a")
    assert is_scope_name("w" * 29) and not is_worker_node_name("w" * 29)
    for value in ("", "-a", "a-", "A", "a_b", "a.b", None, 3):
        assert not is_worker_node_name(value)
