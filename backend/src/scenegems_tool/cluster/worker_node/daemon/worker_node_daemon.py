"""The worker node daemon: the control connection to the control node, and the job runtime.

The worker node needs no control node to start, and no pairing: control node and worker nodes trust the VPN. Its id is
its name, and it dials the configured control node and keeps retrying while that is not up.

Start-up order:
    1. build the WorkerNodeContext and remove instances a crashed predecessor left;
    2. connect: Hello, then the control node's Welcome sets the worker node's instance number, the heartbeat interval and the lease timeout;
    3. serve lease messages until the connection drops, then reconnect with backoff.

Running jobs belong to the LeaseManager, not to a connection, so they keep running
while the daemon reconnects; the next Hello names their leases. A ticker thread renews
leases, sends heartbeats and streams reports whether or not a connection is up; a relay
thread sends the frames of observed simulations, about 10 batches a second at most.

Conditions that no retry can fix stop the daemon with DaemonStopped: the control node speaks
another protocol version, or is not the control node the worker node is configured for.
"""

import logging
import threading
import time
from typing import Callable, Optional

from scenegems_tool.cluster.protocol.codec import MalformedFrame
from scenegems_tool.cluster.protocol.messages import ControlNodeMessage, ProtocolError, ProtocolErrorCode, Welcome
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.version import ProtocolVersionMismatch
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.daemon.control.control_link import ControlLink, LinkClosed
from scenegems_tool.cluster.worker_node.daemon.control.reconnect_backoff import ReconnectBackoff
from scenegems_tool.cluster.worker_node.daemon.control.status_frames import StatusFrames, software_revision
from scenegems_tool.cluster.worker_node.daemon.leases.lease_manager import LeaseManager
from scenegems_tool.cluster.worker_node.daemon.leases.lease_worker import JobRunner
from scenegems_tool.cluster.worker_node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.worker_node.daemon.resource_probe import ResourceProbe
from scenegems_tool.cluster.worker_node.daemon.worker_node_runtime import build_worker_node_context, remove_leftover_instances
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

_logger = logging.getLogger(__name__)

WELCOME_TIMEOUT_S = 30.0
RECEIVE_POLL_S = 0.5  # how often the connection thread looks at the stop event
TICK_S = 0.25
POOL_CHECK_S = 30.0  # how often the daemon looks whether its subsystems' containers still run
RELAY_S = 0.1  # how often observed jobs' frames are relayed to the control node
SHUTDOWN_TIMEOUT_S = 30.0  # time for running jobs to stop and remove their containers


class DaemonStopped(RuntimeError):
    """A condition no reconnect can fix; the message says what the operator must do."""


class _CurrentLink:
    """The sender the lease manager and the ticker use: whatever connection is up, or none."""

    def __init__(self) -> None:
        self.link: Optional[ControlLink] = None

    @property
    def connected(self) -> bool:
        link = self.link
        return link is not None and link.connected

    def send(self, frame: ProtocolFrame) -> bool:
        link = self.link
        return link is not None and link.send(frame)


class WorkerNodeDaemon:
    def __init__(
        self,
        configuration: WorkerNodeConfiguration,
        *,
        run: Optional[JobRunner] = None,
        probe: Optional[ResourceProbe] = None,
        fingerprints: Optional[Callable[[], dict]] = None,
        link_factory: Callable[..., ControlLink] = ControlLink,
        backoff: Optional[ReconnectBackoff] = None,
        worker_node_context: Callable[[WorkerNodeConfiguration, object], WorkerNodeContext] = build_worker_node_context,
        clean_leftovers: bool = True,
        welcome_timeout_s: float = WELCOME_TIMEOUT_S,
        shutdown_timeout_s: float = SHUTDOWN_TIMEOUT_S,
    ):
        self.configuration = configuration
        self._run = run
        self._probe = probe or ResourceProbe(disk_path=RUNTIME_ASSETS_FOLDER)
        self._fingerprints = fingerprints
        self._link_factory = link_factory
        self._backoff = backoff or ReconnectBackoff()
        self._worker_node_context = worker_node_context
        self._clean_leftovers = clean_leftovers
        self._welcome_timeout_s = welcome_timeout_s
        self._shutdown_timeout_s = shutdown_timeout_s
        self._current = _CurrentLink()
        self._heartbeat_interval_s: Optional[float] = None
        self._next_heartbeat = 0.0
        self._next_pool_check: Optional[float] = None  # None until the pools were started, after the Welcome
        self.manager: Optional[LeaseManager] = None
        self.status: Optional[StatusFrames] = None
        self.connected = threading.Event()  # set while a connection is past its Welcome; for tests and health checks

    # Lifecycle

    def run(self, stop: threading.Event) -> None:
        """Run until stop is set (then release the running leases) or DaemonStopped is raised."""
        control_node_id, worker_node_id = self.configuration.control_node_id, self.configuration.worker_node_id
        worker_node = self._worker_node_context(self.configuration)
        if self._clean_leftovers:
            remove_leftover_instances(control_node_id, worker_node_id)
        self.manager = LeaseManager(SlotTable(self.configuration.slots), worker_node, self._current, run=self._run)
        self.status = StatusFrames(
            worker_node_id=worker_node_id,
            worker_node_name=self.configuration.worker_node_name,
            software_revision=software_revision(self.configuration.software_revision),
            machine=self.configuration.machine,
            slots=self.configuration.slots,
            components=self.configuration.components,
            labels=self.configuration.labels,
            resources=self._probe.read,
            fingerprints=self._fingerprints or _local_image_fingerprints,
            leases=self.manager,
        )
        ticker_stop = threading.Event()
        ticker = threading.Thread(target=self._tick_loop, args=(ticker_stop,), name="worker-node-ticker", daemon=True)
        ticker.start()
        relay = threading.Thread(target=self._relay_loop, args=(ticker_stop,), name="worker-node-observation-relay", daemon=True)
        relay.start()
        _logger.info(
            "Worker node %s of control node %s at %s starts with slots %s and components %s",
            worker_node_id,
            control_node_id,
            self.configuration.control_node_url,
            _slots_text(self.configuration),
            ", ".join(sorted(self.configuration.components)),
        )
        try:
            self._connection_loop(stop)
        finally:
            self.manager.shutdown("the worker node daemon stopped", self._shutdown_timeout_s)
            ticker_stop.set()
            ticker.join(timeout=5)
            relay.join(timeout=5)
            link, self._current.link = self._current.link, None
            self.connected.clear()
            if link is not None:
                link.close()
            worker_node.shutdown()
            if self._clean_leftovers:
                remove_leftover_instances(control_node_id, worker_node_id)
            _logger.info("Worker node %s stopped", worker_node_id)

    # Connection

    def _connection_loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            link = self._link_factory(self.configuration.control_node_url)
            try:
                link.open()
                self._handshake(link)
                self._current.link = link
                self.connected.set()
                self._backoff.reset()
                _logger.info("Connected to control node %s at %s", self.configuration.control_node_id, link.url)
                self._serve(link, stop)
            except ProtocolVersionMismatch as error:
                raise DaemonStopped(str(error)) from error
            except (LinkClosed, MalformedFrame) as error:
                _logger.warning("Control connection lost: %s", error)
            finally:
                if not stop.is_set():
                    self.connected.clear()
                    self._current.link = None
                    link.close()
            if stop.is_set():
                break  # the link stays open, so the shutdown can release the leases
            delay = self._backoff.next_delay_s()
            _logger.info("Reconnecting in %.1f s; %d leases keep running", delay, len(self.manager.running_lease_ids()))
            stop.wait(delay)

    def _handshake(self, link: ControlLink) -> None:
        if not link.send(self.status.hello()):
            raise LinkClosed("The connection closed before Hello was sent")
        deadline = time.monotonic() + self._welcome_timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LinkClosed(f"No Welcome from the control node within {self._welcome_timeout_s:g} s")
            message = link.receive(timeout_s=remaining)
            if isinstance(message, Welcome):
                self._welcome(message)
                return
            if isinstance(message, ProtocolError):
                self._protocol_error(message)
                raise LinkClosed(f"The control node refused the Hello: {message.code.value}: {message.message}")
            if message is not None:
                _logger.warning("Ignoring %s before the control node's Welcome", message.type)

    def _welcome(self, welcome: Welcome) -> None:
        configured_control_node = self.configuration.control_node_id
        if welcome.control_node_id != configured_control_node:
            raise DaemonStopped(
                f"The control node at {self.configuration.control_node_url} is {welcome.control_node_id!r}, but this worker node is configured for {configured_control_node!r}: check SCENEGEMS_CONTROL_NODE_URL and SCENEGEMS_CONTROL_NODE_ID"
            )
        self.manager.worker_node.set_instance_number(welcome.instance_number)
        # The subsystems the worker node offers are long lived: they start now, under the worker node's number, not with the first job
        self.manager.worker_node.start_pools()
        self._next_pool_check = time.monotonic() + POOL_CHECK_S
        self.manager.set_lease_timeout(welcome.lease_timeout_s)
        self._heartbeat_interval_s = welcome.heartbeat_interval_s
        self._next_heartbeat = time.monotonic() + welcome.heartbeat_interval_s

    def _serve(self, link: ControlLink, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                message = link.receive(timeout_s=RECEIVE_POLL_S)
            except MalformedFrame as error:
                _logger.warning("Ignoring a malformed frame from the control node: %s", error)
                continue
            if message is not None:
                self._dispatch(message)

    def _dispatch(self, message: ControlNodeMessage) -> None:
        if self.manager.handle(message):
            return
        if isinstance(message, ProtocolError):
            self._protocol_error(message)
            _logger.warning("Protocol error from the control node: %s: %s", message.code.value, message.message)
        elif isinstance(message, Welcome):
            self._welcome(message)

    def _protocol_error(self, error: ProtocolError) -> None:
        if error.code == ProtocolErrorCode.UNAUTHORIZED:
            raise DaemonStopped(f"The control node refused this worker node: {error.message}")
        if error.code == ProtocolErrorCode.VERSION_MISMATCH:
            raise DaemonStopped(f"The control node speaks another protocol version: {error.message}")

    # Ticker

    def _tick_loop(self, stop: threading.Event) -> None:
        while not stop.wait(TICK_S):
            try:
                self.manager.tick()
                self._heartbeat()
                self._check_pools()
            except Exception:
                _logger.exception("Worker node ticker failed; continuing")

    def _relay_loop(self, stop: threading.Event) -> None:
        while not stop.wait(RELAY_S):
            try:
                self.manager.relay_observations()
            except Exception:
                _logger.exception("Observation relay failed; continuing")

    def _check_pools(self) -> None:
        """Every POOL_CHECK_S: a subsystem whose container is gone is started again."""
        if self._next_pool_check is None or time.monotonic() < self._next_pool_check:
            return
        self._next_pool_check = time.monotonic() + POOL_CHECK_S
        self.manager.worker_node.check_pools()

    def _heartbeat(self) -> None:
        if self._heartbeat_interval_s is None or not self._current.connected:
            return
        now = time.monotonic()
        if now >= self._next_heartbeat:
            self._next_heartbeat = now + self._heartbeat_interval_s
            self._current.send(self.status.heartbeat())


def _local_image_fingerprints() -> dict:
    from scenegems_tool.cluster.fingerprints.labels import read_image_fingerprints

    return read_image_fingerprints()


def _slots_text(configuration: WorkerNodeConfiguration) -> str:
    return ", ".join(f"{job_type.value}:{slots}" for job_type, slots in sorted(configuration.slots.items(), key=lambda item: item[0].value))
