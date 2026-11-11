import pytest

from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION, ProtocolVersionMismatch, ensure_compatible


def test_same_version_is_accepted():
    ensure_compatible(PROTOCOL_VERSION)


@pytest.mark.parametrize("received", [PROTOCOL_VERSION + 1, 0, None, "1"])
def test_other_versions_are_rejected(received):
    with pytest.raises(ProtocolVersionMismatch) as error:
        ensure_compatible(received)
    assert error.value.received == received
    assert error.value.expected == PROTOCOL_VERSION


def test_mismatch_message_names_both_versions_and_the_fix():
    message = str(ProtocolVersionMismatch(7))
    assert "received 7" in message
    assert f"speaks {PROTOCOL_VERSION}" in message
    assert "same SceneGEMS revision" in message


def test_the_worker_nodes_instance_number_is_version_10():
    # Version 6: slots and components in the Hello, components in the requirements, one simulation job type.
    # Version 7: the design_space_exploration job type, and list result fields stored as one artifact per item; an older worker node is refused by its version
    # Version 8: control node and worker node in the field names, the control socket path and the artifact header
    # Version 9: asv_system as the key of a vessel's stack and in the component ids
    # Version 10: the worker node's instance number in the Welcome, which names its pooled services on the broker
    assert PROTOCOL_VERSION == 10
