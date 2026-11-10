"""Wire protocol between the containers of a vessel stack: one JSON object per line over TCP.

Every layer of a vessel stack that SceneGEMS steps itself runs in its own container and serves
this protocol: an ASV system, a controller or a simulator. The runner of the stack connects to
each of them, owns the lockstep clock and carries the messages between them, so a component
never talks to another one directly and needs to know nothing about the rest of the stack.

A component answers every request with exactly one reply and does nothing in between, so a run
is a function of the requests alone. Floats travel as JSON numbers in Python's shortest
round-trip form and arrive bit for bit.

Common to every role:

    -> {"op": "hello"}
    <- {"op": "hello", "protocol": 1, "role": "<role>", "implementation": "<name>"}
    -> {"op": "close"}                      (no reply; the component waits for the next runner)
    <- {"op": "error", "message": ".."}     (a failed request; the connection ends)

ASV system (ROLE_ASV_SYSTEM), one container per vessel:

    -> {"op": "start", "seed": 7, "vessel": {"id": 0, "length": .., "max_speed": .., "max_acceleration": .., "max_angular_speed": ..},
        "config": {..}}                     (config belongs to the implementation)
    <- {"op": "started", "participant_id": "replay/0"}
       or, from software that hands its controller a waypoint mission instead of commands:
    <- {"op": "started", "participant_id": "replay/0", "mission": {"time_step": 1.0, "waypoints": [[x, y, speed, heading], ..]}}
    -> {"op": "step", "index": 0, "time": 0.0, "target_time": 1.0, "own": [x, y, speed, heading], "targets": {"<actor id>": [x, y, speed, heading]}}
    <- {"op": "command", "heading": .., "speed": ..}
    -> {"op": "report"}
    <- {"op": "report", "report": {..}}     (what the software wants in the run record; may be empty)

Controller (ROLE_CONTROLLER), one container per vessel; its start, guide and step messages belong
to the implementation (control_layers/custom/custom_controller_server.py).

Simulator (ROLE_SIMULATOR), one container per scenario; its start and step messages belong to the
implementation (simulation_layers/kinematic/kinematic_sim_server.py, and the gz-transport actuator
of the Gazebo image, which had this shape first).

This file imports only the standard library: an image that holds one component and no SceneGEMS
backend copies it next to the component's server (deploy/images/usv_navigation).
"""

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

PROTOCOL_VERSION = 1
ROLE_ASV_SYSTEM = "asv_system"
ROLE_CONTROLLER = "controller"
ROLE_SIMULATOR = "simulator"

Message = Dict[str, Any]
StateRow = List[float]  # [x, y, speed, heading] in the local frame


class WireError(RuntimeError):
    """A component refused a request, spoke another protocol or closed the connection."""


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int

    def __str__(self) -> str:
        return f"{self.host}:{self.port}"


def state_row(state: Any) -> StateRow:
    """The wire form of anything with x, y, speed and heading (an ActorState)."""
    return [float(state.x), float(state.y), float(state.speed), float(state.heading)]


def state_rows(states: Mapping[int, Any]) -> Dict[str, StateRow]:
    """States by actor id in wire form; JSON object keys are strings."""
    return {str(actor_id): state_row(state) for actor_id, state in states.items()}


class Session:
    """One runner's conversation with a component. A subclass answers op X in on_X(request) and returns the reply."""

    def handle(self, request: Message) -> Message:
        handler = getattr(self, f"on_{request.get('op')}", None)
        if handler is None:
            raise WireError(f"unknown op {request.get('op')!r}")
        return handler(request)


class LineServer:
    """Serves one component: runners connect one at a time, and each connection gets a fresh session."""

    def __init__(self, role: str, implementation: str, session_factory: Callable[[], Session], *, host: str = "0.0.0.0", port: int = 0):
        self.role = role
        self.implementation = implementation
        self._session_factory = session_factory
        self._listener = socket.create_server((host, port))
        self.port: int = self._listener.getsockname()[1]
        self._closed = threading.Event()

    def serve_forever(self) -> None:
        while not self._closed.is_set():
            try:
                connection, _ = self._listener.accept()
            except OSError:
                return  # closed
            with connection:
                connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._serve_connection(connection)

    def start_in_thread(self) -> "LineServer":
        threading.Thread(target=self.serve_forever, name=f"{self.implementation}_{self.role}_server", daemon=True).start()
        return self

    def close(self) -> None:
        self._closed.set()
        self._listener.close()

    def __enter__(self) -> "LineServer":
        return self.start_in_thread()

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _serve_connection(self, connection: socket.socket) -> None:
        reader = connection.makefile("r", encoding="utf-8", newline="\n")
        writer = connection.makefile("w", encoding="utf-8", newline="\n")
        session = self._session_factory()
        try:
            for line in reader:
                request = json.loads(line)
                if request.get("op") == "close":
                    return
                try:
                    reply = self._hello() if request.get("op") == "hello" else session.handle(request)
                except Exception as error:  # the runner gets the reason, and the next runner a fresh session
                    _send(writer, {"op": "error", "message": f"{type(error).__name__}: {error}"})
                    return
                _send(writer, reply)
        except (OSError, ValueError):
            return  # the runner went away mid-line

    def _hello(self) -> Message:
        return {"op": "hello", "protocol": PROTOCOL_VERSION, "role": self.role, "implementation": self.implementation}


class LineClient:
    """The runner's side of one component."""

    def __init__(self, endpoint: Endpoint, role: str):
        self.endpoint = endpoint
        self.role = role
        self.implementation: Optional[str] = None
        self._socket: Optional[socket.socket] = None
        self._reader: Any = None
        self._writer: Any = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self, timeout_s: float = 300.0) -> None:
        """Connect and exchange hello, retrying while the component's container starts. Only an answered hello counts as connected."""
        deadline = time.monotonic() + timeout_s
        last_error: Optional[BaseException] = None
        while True:
            try:
                self._socket = socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=5.0)
                self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._reader = self._socket.makefile("r", encoding="utf-8", newline="\n")
                self._writer = self._socket.makefile("w", encoding="utf-8", newline="\n")
                hello = self.request({"op": "hello"})
                self._socket.settimeout(None)
                break
            except (OSError, ValueError) as error:
                last_error = error
                self._drop()
                if time.monotonic() >= deadline:
                    raise WireError(f"no {self.role} at {self.endpoint} within {timeout_s:g} s (last error: {last_error})") from error
                time.sleep(0.2)
        if hello.get("protocol") != PROTOCOL_VERSION or hello.get("role") != self.role:
            self.close()
            raise WireError(f"{self.endpoint} is a {hello.get('role')} speaking protocol {hello.get('protocol')}; expected a {self.role} speaking protocol {PROTOCOL_VERSION}")
        self.implementation = hello.get("implementation")

    def request(self, request: Message) -> Message:
        if self._writer is None:
            raise WireError(f"{self.endpoint}: not connected")
        _send(self._writer, request)
        line = self._reader.readline()
        if not line:
            raise ConnectionError(f"{self.endpoint}: the {self.role} closed the connection")
        reply = json.loads(line)
        if reply.get("op") == "error":
            raise WireError(f"{self.role} at {self.endpoint}: {reply.get('message')}")
        return reply

    def close(self) -> None:
        if self._writer is not None:
            try:
                _send(self._writer, {"op": "close"})
            except OSError:
                pass
        self._drop()

    def _drop(self) -> None:
        if self._socket is not None:
            self._socket.close()
        self._socket = self._reader = self._writer = None


def serve_component(role: str, implementation: str, session_factory: Callable[[], Session], argv: Optional[Sequence[str]] = None, *, default_port: int) -> None:
    """Entry point of a component's container: serve it on --port until the container stops."""
    import argparse

    parser = argparse.ArgumentParser(description=f"SceneGEMS {implementation} {role} component")
    parser.add_argument("--port", type=int, default=default_port)
    arguments = parser.parse_args(argv)
    server = LineServer(role, implementation, session_factory, port=arguments.port)
    print(f"{implementation} {role} listening on port {server.port}", flush=True)
    server.serve_forever()


def _send(writer: Any, message: Message) -> None:
    writer.write(json.dumps(message) + "\n")
    writer.flush()
