"""The lockstep wire protocol: hello, one reply per request, errors, a fresh session per runner, and floats bit for bit."""

import math
import struct
import subprocess
import sys

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts import lockstep_wire
from scenegems_tool.vessel_stack.contracts.lockstep_wire import PROTOCOL_VERSION, ROLE_ASV_SOFTWARE, ROLE_SIMULATOR, Endpoint, LineClient, LineServer, Session, WireError, state_row, state_rows


class EchoSession(Session):
    """Counts its requests, so a test can tell one session from the next."""

    def __init__(self):
        self.requests = 0

    def on_echo(self, request):
        self.requests += 1
        return {"op": "echo", "value": request["value"], "requests": self.requests}

    def on_fail(self, request):
        raise ValueError("this request cannot be served")


@pytest.fixture
def server():
    with LineServer(ROLE_SIMULATOR, "echo", EchoSession, host="127.0.0.1") as server:
        yield server


def connect(server, role=ROLE_SIMULATOR) -> LineClient:
    client = LineClient(Endpoint("127.0.0.1", server.port), role)
    client.connect(timeout_s=5.0)
    return client


def test_hello_names_the_protocol_the_role_and_the_implementation(server):
    client = connect(server)
    assert client.connected and client.implementation == "echo"
    assert client.request({"op": "hello"}) == {"op": "hello", "protocol": PROTOCOL_VERSION, "role": ROLE_SIMULATOR, "implementation": "echo"}
    client.close()


def test_a_component_of_another_role_is_refused(server):
    with pytest.raises(WireError, match="expected a asv_software"):
        connect(server, role=ROLE_ASV_SOFTWARE)


def test_nothing_listening_fails_after_the_timeout():
    with LineServer(ROLE_SIMULATOR, "echo", EchoSession, host="127.0.0.1") as closed:
        port = closed.port
    client = LineClient(Endpoint("127.0.0.1", port), ROLE_SIMULATOR)
    with pytest.raises(WireError, match="no simulator at"):
        client.connect(timeout_s=0.3)


def test_every_request_gets_one_reply(server):
    client = connect(server)
    assert [client.request({"op": "echo", "value": value})["requests"] for value in "abc"] == [1, 2, 3]
    client.close()


@pytest.mark.parametrize("value", [0.1, 1 / 3, math.pi, 1e-320, -0.0, 1.7976931348623157e308, 123456789.12345679])
def test_floats_arrive_bit_for_bit(server, value):
    client = connect(server)
    echoed = client.request({"op": "echo", "value": value})["value"]
    assert struct.pack("<d", echoed) == struct.pack("<d", value)
    client.close()


def test_a_failed_request_answers_an_error_and_ends_the_connection(server):
    client = connect(server)
    with pytest.raises(WireError, match="ValueError: this request cannot be served"):
        client.request({"op": "fail"})
    with pytest.raises((ConnectionError, OSError)):
        client.request({"op": "echo", "value": 1})


def test_an_unknown_op_is_an_error(server):
    client = connect(server)
    with pytest.raises(WireError, match="unknown op 'dance'"):
        client.request({"op": "dance"})


def test_the_next_runner_gets_a_fresh_session(server):
    first = connect(server)
    assert first.request({"op": "echo", "value": 1})["requests"] == 1
    first.close()
    second = connect(server)
    assert second.request({"op": "echo", "value": 1})["requests"] == 1
    second.close()


def test_a_request_before_connecting_is_refused():
    with pytest.raises(WireError, match="not connected"):
        LineClient(Endpoint("127.0.0.1", 1), ROLE_SIMULATOR).request({"op": "hello"})


def test_states_travel_as_rows_keyed_by_actor_id():
    state = ActorState(1.5, -2.0, 3, 0.25)
    assert state_row(state) == [1.5, -2.0, 3.0, 0.25] and all(type(value) is float for value in state_row(state))
    assert state_rows({7: state}) == {"7": [1.5, -2.0, 3.0, 0.25]}


def test_the_module_needs_only_the_standard_library():
    """An image with one component and no SceneGEMS backend copies this file, so it must import alone."""
    code = "import runpy, sys; runpy.run_path(sys.argv[1]); print(sorted(name for name in sys.modules if name.split('.')[0] in ('numpy', 'scenegems_tool', 'concrete_level', 'utils')))"
    output = subprocess.run([sys.executable, "-I", "-c", code, lockstep_wire.__file__], capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"
