"""The per-job stack of a simulation: every layer of every vessel's stack in its own container, plus the runner.

Every simulation runner builds its stack here. The instance is resolved first, so a stack the
worker node cannot run fails the job before anything starts. The vessel stack then brings its
containers (vessel_stack/simulation_docker_stack.py): the simulator of the scenario, and per
vessel its controller and its ASV system. The runner, from the simulation subsystem image, joins
their network and steps them (vessel_stack/hosting.py, ContainerHosting).

An instance with a real vessel runs every vessel through its ArduAgent over MQTT
(subsystems/simulation/arduagent_simulation_driver.py): each simulated vessel then has MAVProxy and
an ArduAgent beside its SITL, and those and the runner are given the job's broker. On the cluster's
broker they join the network the worker node's pooled services reach it on; an external broker is
dialled from the stack's own network.

The generated files of a simulator (Gazebo's world, SITL's parameters) reach it through the
runtime assets volume, so a stack is built where that volume is mounted at
RUNTIME_ASSETS_FOLDER: the container of the worker node's simulation subsystem, whose tasks
build and start their stacks (subsystems/simulation/simulation_worker.py).
"""

from typing import TYPE_CHECKING, Dict, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, JobStack, runner_service
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.vessel_stack.contracts.stack_services import STACK_NETWORK
from utils.docker_compose_network import attach_broker_network_to_service, scenegems_broker_network_definition

if TYPE_CHECKING:
    from concrete_level.models.trajectories import Trajectories
    from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
    from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig


def ground_control_ports(instance: "SimulationInstanceConfig") -> Dict[str, Tuple[str, int]]:
    """By agent id, the MAVProxy service of every Mission Planner vessel and the container port its ground control station connects to."""
    from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import GCS_CONTAINER_PORT, MISSION_PLANNER_GCS_PORT, MISSION_PLANNER_MAVLINK_PORT
    from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import gcs_mavproxy_service_name
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    # Both adapters give the vessel a MAVProxy with the ground station's endpoint: the lockstep one and, beside a real vessel, ArduAgent's
    ground_station_adapters = {MISSION_PLANNER_GCS_PORT.id, MISSION_PLANNER_MAVLINK_PORT.id}
    resolver = default_resolver()
    ports: Dict[str, Tuple[str, int]] = {}
    for agent_id, vessel in instance.simulated_vessels.items():
        adapter = resolver.resolve(vessel.stack, vessel.adapter_ids).asv_adapter
        if adapter is not None and adapter.id in ground_station_adapters:
            ports[agent_id] = (gcs_mavproxy_service_name(vessel.require_connection().agent_name), GCS_CONTAINER_PORT)
    return ports


def arduagent_services(instance: "SimulationInstanceConfig") -> Tuple[str, ...]:
    """The MAVProxy and ArduAgent services of the simulated vessels ArduAgent drives: the stack's containers that talk to the broker."""
    from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import ARDUAGENT_ADAPTER_IDS
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    resolver = default_resolver()
    services = []
    for vessel in instance.simulated_vessels.values():
        adapter = resolver.resolve(vessel.stack, vessel.adapter_ids).asv_adapter
        if adapter is not None and adapter.id in ARDUAGENT_ADAPTER_IDS:
            name = vessel.require_connection().agent_name
            services.extend((f"{name}_mavproxy", f"{name}_arduagent"))
    return tuple(services)


def build_vessel_job_stack(
    job: JobSpec,
    worker_node: WorkerNodeContext,
    instance: "SimulationInstanceConfig",
    trajectories: "Trajectories",
    geofence: "Geofence",
    *,
    attended: bool = False,
    mqtt_connection: Optional["MQttConnectionInfo"] = None,
    service_name: Optional[str] = None,
) -> JobStack:
    """Resolve the instance, write its generated files into the job's folder and assemble the stack: its containers and the runner.

    attended: an operator is beside the run, so the stacks that need one are allowed (Mission Planner), and the ground
    control station port of each such vessel's MAVProxy stays published.

    mqtt_connection: the broker of a run with a real vessel, when it is not the cluster's (an external one such as
    WARA-PS's). service_name: the name the runner has on that broker. Only an instance with a real vessel talks to a
    broker at all, so only its runner gets the connection.
    """
    from scenegems_tool.messaging.mqtt_client import SERVICE_NAME_VARIABLE, mqtt_container_environment
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
    from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts, write_simulation_gen_files

    try:
        default_resolver().require_instance(instance, attended=attended)
    except StackUnavailableError as error:
        raise JobFailed(f"Simulation stack rejected: {error}", retryable=False) from error
    scope = worker_node.job_scope(job)
    gen_folder = f"{scope.folder}/gen"
    pending_writes, stack_compose = build_simulation_docker_stack_artifacts(instance, trajectories, mqtt_connection or worker_node.mqtt_connection, geofence, headless=True, gen_folder=gen_folder)
    write_simulation_gen_files(pending_writes, gen_folder)
    stack_services = list(stack_compose["services"])
    networks = dict(stack_compose["networks"])
    on_broker = instance.has_real_vessel
    environment = None
    if on_broker:
        environment = {"PYTHONUNBUFFERED": "1", **mqtt_container_environment(mqtt_connection or worker_node.mqtt_connection)}
        if service_name:
            environment[SERVICE_NAME_VARIABLE] = service_name
    services = {
        **stack_compose["services"],
        RUNNER_SERVICE: runner_service(subsystem_image(Subsystem.SIMULATION), networks=[STACK_NETWORK], depends_on=stack_services, environment=environment),
    }
    if on_broker and mqtt_connection is None:
        # The cluster's broker is reached on the network the worker node's pooled services reach it on
        networks.update(scenegems_broker_network_definition(worker_node.broker_network))
        for name in (RUNNER_SERVICE, *arduagent_services(instance)):
            attach_broker_network_to_service(services[name])
    published = [service for service, _ in ground_control_ports(instance).values()] if attended else []
    return JobStack(scope, services, networks=networks, volumes=stack_compose.get("volumes"), published=published)
