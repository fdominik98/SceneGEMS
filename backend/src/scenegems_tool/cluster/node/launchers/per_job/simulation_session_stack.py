"""The workbench's simulation stack: one compose stack per live session.

It holds the generated vessel stack, every layer in its own container (the simulator of the
scenario, and per vessel its controller and its ASV software: Gazebo or the kinematic simulator,
SITL or the custom controller, ArduAgent with MAVProxy, replay or USV Navigation), and the
scenario execution service, which the workbench drives over MQTT. Every live session has its own
scope (InstanceScope.live_session: node `workbench`, instance `live-<session>`), and the
stack's compose project, container names, networks and generated files come from it, so
several live sessions run side by side on one machine. On the master's broker the session's
topics are scoped too (gateway/socket_session.py); the node runs cluster simulations as
per-job stacks instead (per_job/job_stack.py).

The scenario execution service joins the vessel stack's network, since an instance of
simulated vessels is driven by its lockstep runner from there, which steps the stack's
containers (subsystems/scenario_execution/lockstep_simulation_driver.py). Host ports are published only where a person
connects: Docker picks a free host port for each Mission Planner vessel's ground control
station, which is read back once the stack is up and handed to on_ground_control_ports.

Within one session a new simulation takes ownership of the session's stack; a teardown
scheduled by an older owner is skipped, so replacing a simulation never removes the stack
its successor just started. Ownership is per session scope: no session touches another's
stack. Stacks an earlier process left behind are removed once per process.
"""

import base64
import json
import logging
import os
import shutil
import threading
import uuid
from typing import Callable, Dict, List, Mapping, Optional

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.cluster.node.instance_scope import InstanceScope, live_session_project_prefix
from scenegems_tool.cluster.node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.node.launchers.docker_cli import compose_projects_with_prefix, force_remove_compose_project, remove_compose_project_networks
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.gateway.protocol import make_simulation_models_body
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_scenario_execution_service import SCENARIO_EXECUTION_SERVICE_TOPIC
from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import GCS_CONTAINER_PORT, MISSION_PLANNER_GCS_PORT
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import gcs_mavproxy_service_name
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.simulation_docker_stack import SIMULATION_COMPOSE_PROJECT, build_simulation_docker_stack_artifacts, write_simulation_gen_files
from utils.docker_compose_network import attach_broker_network_to_compose
from utils.file_system_utils import docker_volume_path, merge_compose_volumes, runtime_assets_volume_mount

# The fixed project names of the single stack per machine, before live sessions had scopes.
LEGACY_COMPOSE_PROJECTS = ("scenegems-scenario-execution-subsystem", SIMULATION_COMPOSE_PROJECT)
DEFAULT_MASTER_ID = "local"  # a gateway without a master (SCENEGEMS_MASTER_ID unset)
SERVICE_NAME = "scenario_execution"
SERVICE_NETWORK = "scenario_execution_net"
SERVICE_CPU = 2
GROUND_CONTROL_PORT_ATTEMPTS = 30  # seconds to wait for Docker to publish the ground station ports after up
GroundControlPortsObserver = Callable[[Dict[str, int]], None]  # host port by agent id
_logger = logging.getLogger(__name__)


def new_live_session_scope(environ: Optional[Mapping[str, str]] = None) -> InstanceScope:
    """A fresh scope for one live session of this server's master (SCENEGEMS_MASTER_ID, `local` without one)."""
    environ = os.environ if environ is None else environ
    master_id = environ.get("SCENEGEMS_MASTER_ID", "").strip() or DEFAULT_MASTER_ID
    return InstanceScope.live_session(master_id, uuid.uuid4().hex[:8])


def session_gen_folder(scope: InstanceScope) -> str:
    """The session's generated files (world, vessel models, parameters, trajectories), on the runtime assets volume."""
    return f"{scope.folder}/gen"


def session_trajectories_file(scope: InstanceScope) -> str:
    return f"{session_gen_folder(scope)}/trajectories.json"


def session_compose_project(scope: InstanceScope) -> ComposeProject:
    return ComposeProject(scope.compose_project, f"{scope.folder}/docker-compose.yml")


class _StackOwnership:
    """The owner generation and the lock of every session stack this process started, by compose project."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generations: Dict[str, int] = {}
        self._project_locks: Dict[str, threading.Lock] = {}

    def claim(self, project: str) -> int:
        with self._lock:
            self._generations[project] = self._generations.get(project, 0) + 1
            self._project_locks.setdefault(project, threading.Lock())
            return self._generations[project]

    def is_current(self, project: str, generation: Optional[int]) -> bool:
        with self._lock:
            return generation is None or self._generations.get(project) == generation

    def project_lock(self, project: str) -> threading.Lock:
        with self._lock:
            return self._project_locks.setdefault(project, threading.Lock())

    def projects(self) -> List[str]:
        with self._lock:
            return list(self._generations)


_ownership = _StackOwnership()
_leftover_sweep_lock = threading.Lock()
_leftover_sweep_started = False


def claim_stack_ownership(scope: InstanceScope) -> int:
    """Mark a new owner of the session's stack; scheduled destroys of its older owners are skipped."""
    return _ownership.claim(scope.compose_project)


def _remove_project(project: str, folder: Optional[str] = None) -> None:
    force_remove_compose_project(project)
    remove_compose_project_networks(project)
    if folder and os.path.isdir(folder):
        shutil.rmtree(folder, ignore_errors=True)


def force_destroy_session_stack(scope: InstanceScope) -> None:
    """Fast teardown of one session's stack: its containers by compose project label, its networks and its files."""
    _remove_project(scope.compose_project, scope.folder)


def schedule_force_destroy_session_stack(scope: InstanceScope, owner_generation: Optional[int] = None) -> None:
    """Tear down the session's stack on a background thread, unless a newer owner took it over by then."""

    def _run_destroy() -> None:
        try:
            with _ownership.project_lock(scope.compose_project):
                if not _ownership.is_current(scope.compose_project, owner_generation):
                    return
                force_destroy_session_stack(scope)
        except BaseException:
            _logger.exception("Background live session stack destroy failed")

    threading.Thread(target=_run_destroy, name=f"{scope.compose_project}_destroy", daemon=True).start()


def force_destroy_session_stacks() -> None:
    """Every session stack this process started, and the fixed-name stacks of older versions (process exit)."""
    for project in _ownership.projects():
        _remove_project(project)
    for project in LEGACY_COMPOSE_PROJECTS:
        _remove_project(project)


def remove_leftover_session_stacks(master_id: str) -> None:
    """The stacks of this master's live sessions that no session of this process owns (an earlier process left them), and the legacy ones."""
    owned = set(_ownership.projects())
    for project in compose_projects_with_prefix(live_session_project_prefix(master_id)):
        if project not in owned:
            _remove_project(project)
    for project in LEGACY_COMPOSE_PROJECTS:
        _remove_project(project)


def schedule_leftover_sweep(environ: Optional[Mapping[str, str]] = None) -> None:
    """Once per process, in the background: remove_leftover_session_stacks for this server's master."""
    global _leftover_sweep_started
    with _leftover_sweep_lock:
        if _leftover_sweep_started:
            return
        _leftover_sweep_started = True
    master_id = new_live_session_scope(environ).master_id

    def _run_sweep() -> None:
        try:
            remove_leftover_session_stacks(master_id)
        except BaseException:
            _logger.exception("Live session leftover sweep failed")

    threading.Thread(target=_run_sweep, name="live_session_leftover_sweep", daemon=True).start()


class SimulationSessionStack:
    """Spawns and tears down one live session's compose stack: the vessel stack and the scenario execution service."""

    service_topic = SCENARIO_EXECUTION_SERVICE_TOPIC  # relative: the session's MQTT clients add its topic prefix

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
        on_ground_control_ports: Optional[GroundControlPortsObserver] = None,
        scope: Optional[InstanceScope] = None,
    ):
        self.scope = scope or new_live_session_scope()
        self.project = session_compose_project(self.scope)
        self._on_ground_control_ports = on_ground_control_ports
        self.compose_filename = self.project.compose_filename
        self._destroyed = False
        self._shutdown = threading.Event()
        self._stack_generation = claim_stack_ownership(self.scope)
        self._spawn_thread = threading.Thread(
            target=self._run_spawn,
            args=(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step),
            name=f"{self.scope.compose_project}_spawn",
            daemon=True,
        )
        self._spawn_thread.start()

    def _run_spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        # The whole spawn holds the session's lock: a destroy scheduled meanwhile runs after it
        # and then sees whether this stack is still the session's current one.
        with _ownership.project_lock(self.scope.compose_project):
            try:
                if self._shutdown.is_set() or not _ownership.is_current(self.scope.compose_project, self._stack_generation):
                    return
                force_destroy_session_stack(self.scope)  # the previous simulation of this session
                if self._shutdown.is_set():
                    return
                self._spawn(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step)
            except BaseException:
                _logger.exception("Live session stack spawn failed")
                force_destroy_session_stack(self.scope)
                return
        self._report_ground_control_ports(simulation_config)

    def _spawn(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
    ) -> None:
        gen_folder = session_gen_folder(self.scope)
        pending_writes, stack_compose = build_simulation_docker_stack_artifacts(
            simulation_config,
            trajectories,
            mqtt_connection,
            reference_geofence,
            embedded_in_subsystem=True,
            gen_folder=gen_folder,
        )
        write_simulation_gen_files(pending_writes, gen_folder)
        self._verify_gen_files(pending_writes)

        unified_compose = build_unified_compose(stack_compose, mqtt_connection, reference_geofence, simulation_config, time_step, self.scope)
        self.project.write(unified_compose)
        self.project.up("--force-recreate")

    def _report_ground_control_ports(self, simulation_config: SimulationInstanceConfig) -> None:
        services = ground_control_services(simulation_config)
        if not services or self._on_ground_control_ports is None or self._shutdown.is_set():
            return
        ports: Dict[str, int] = {}
        for _ in range(GROUND_CONTROL_PORT_ATTEMPTS):
            for agent_id, service in services.items():
                if agent_id not in ports:
                    port = self.project.published_port(service, GCS_CONTAINER_PORT)
                    if port is not None:
                        ports[agent_id] = port
            if len(ports) == len(services) or self._shutdown.wait(1.0):
                break
        if ports and not self._shutdown.is_set():
            self._on_ground_control_ports(ports)

    def _verify_gen_files(self, pending_writes: list[tuple[str, str]]) -> None:
        missing = [path for path, _ in pending_writes if not os.path.isfile(path)]
        if missing:
            raise FileNotFoundError(f"Simulation gen files missing before compose up: {missing}")

    def cancel(self) -> None:
        """Stop the spawn and leave the stack to the session's next simulation, which takes it over (simulation replaced)."""
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()

    def destroy(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self._shutdown.set()
        schedule_force_destroy_session_stack(self.scope, owner_generation=self._stack_generation)


def ground_control_services(simulation_config: SimulationInstanceConfig) -> Dict[str, str]:
    """The MAVProxy service of every Mission Planner vessel on its ground control station port, by agent id."""
    resolver = default_resolver()
    services = {}
    for agent_id, vessel in simulation_config.simulated_vessels.items():
        adapter = resolver.resolve(vessel.stack, vessel.adapter_ids).asv_adapter
        if adapter is not None and adapter.id == MISSION_PLANNER_GCS_PORT.id:
            services[agent_id] = gcs_mavproxy_service_name(vessel.require_connection().agent_name)
    return services


def build_unified_compose(
    stack_compose: dict,
    mqtt_connection: MQttConnectionInfo,
    reference_geofence: Geofence,
    simulation_config: SimulationInstanceConfig,
    time_step: int,
    scope: InstanceScope,
) -> dict:
    """The vessel stack's services plus the scenario execution service that drives them, named from the session's scope.

    Service keys stay as generated, so the services still reach each other by them (SITL's
    `gazebo`, MAVProxy's `<agent>`) on the session's own networks.
    """
    simulation_config_b64 = base64.b64encode(json.dumps(make_simulation_models_body(simulation_config)).encode("utf-8")).decode("ascii")

    services = {key: {**service, "container_name": scope.container_name(key)} for key, service in stack_compose["services"].items()}
    agent_service_names = list(services)
    stack_networks = {key: {**definition, "name": scope.network_name(key)} for key, definition in stack_compose.get("networks", {}).items()}
    scenario_execution_service = {
        "image": subsystem_image(Subsystem.SCENARIO_EXECUTION),
        "container_name": scope.container_name(SERVICE_NAME),
        "hostname": SERVICE_NAME,
        **({"depends_on": agent_service_names} if agent_service_names else {}),
        "environment": {
            **subsystem_environment(mqtt_connection, reference_geofence),
            "SIMULATION_CONFIG_JSON_B64": simulation_config_b64,
            "TRAJECTORIES_PATH": docker_volume_path(session_trajectories_file(scope)),
            "TIME_STEP": str(time_step),
        },
        "cpus": SERVICE_CPU,
        "restart": "unless-stopped",
        "extra_hosts": ["host.docker.internal:host-gateway"],
        "volumes": [runtime_assets_volume_mount(read_only=True)],
        # The vessel stack's network too: the lockstep runners reach SITL and Gazebo there.
        "networks": [SERVICE_NETWORK, *stack_networks],
    }

    return merge_compose_volumes(
        attach_broker_network_to_compose(
            {
                "services": {
                    **services,
                    SERVICE_NAME: scenario_execution_service,
                },
                "networks": {
                    SERVICE_NETWORK: {"name": scope.network_name(SERVICE_NETWORK), "driver": "bridge"},
                    **stack_networks,
                },
            }
        )
    )
