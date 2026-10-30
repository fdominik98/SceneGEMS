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


def test_the_split_ardupilot_simulation_is_version_5():
    # Version 5: simulation.ardupilot_sim and simulation.gazebo replace simulation.ardupilot, so an older node is refused by its version
    assert PROTOCOL_VERSION == 5
