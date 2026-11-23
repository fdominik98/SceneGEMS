"""The pod of a simulation run: every layer of every vessel's stack in its own container, plus the runner.

Every simulation runner builds its run's pod here. The instance is resolved first, so a stack the
worker node cannot run fails the job before anything starts. The vessel stack then brings its
services (vessel_stack/simulation_docker_stack.py): the simulator of the scenario, and per
vessel its controller and its ASV system. The runner, from the simulation subsystem image, steps
them (vessel_stack/hosting.py, ContainerHosting). The services become the containers of one pod
(launchers/per_job/run_pod.py), which share its network: each reaches the others by its service name.

An instance with a real vessel runs every vessel through its ArduAgent over MQTT
(subsystems/simulation/arduagent_simulation_driver.py): each simulated vessel then has MAVProxy and
an ArduAgent beside its SITL, and those and the runner are given the job's broker in their environment:
the cluster's broker by its service name, or an external one.

A run that is judged while it runs (monitor live) has its scenes judged by the worker node's monitoring
subsystem: its runner is told which one and the cluster's broker in its environment, whatever broker
its vessels use (jobs/pooled_series.py).

The generated files of a simulator (Gazebo's world, SITL's parameters) reach it through the worker
node's runtime folder, so a run's pod is built where that folder is mounted at RUNTIME_ASSETS_FOLDER:
the container of the worker node's simulation subsystem, whose tasks build and start their runs' pods
(subsystems/simulation/simulation_worker.py).
"""

from typing import TYPE_CHECKING, Dict, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUNNER_SERVICE, RunPod, runner_service
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

if TYPE_CHECKING:
    from concrete_level.models.trajectories import Trajectories
    from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
    from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig


def ground_control_ports(instance: "SimulationInstanceConfig") -> Dict[str, Tuple[str, int]]:
    """By agent id, the MAVProxy service of every Mission Planner vessel and the container port its ground control station connects to."""
    from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_GCS_PORT, MISSION_PLANNER_MAVLINK_PORT
    from scenegems_tool.vessel_stack.contracts.stack_services import gcs_container_port
    from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import gcs_mavproxy_service_name
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver

    # Both adapters give the vessel a MAVProxy with the ground station's endpoint: the lockstep one and, beside a real vessel, ArduAgent's
    ground_station_adapters = {MISSION_PLANNER_GCS_PORT.id, MISSION_PLANNER_MAVLINK_PORT.id}
    resolver = default_resolver()
    ports: Dict[str, Tuple[str, int]] = {}
    for agent_id, vessel in instance.simulated_vessels.items():
        adapter = resolver.resolve(vessel.stack, vessel.adapter_ids).asv_adapter
        if adapter is not None and adapter.id in ground_station_adapters:
            ports[agent_id] = (gcs_mavproxy_service_name(vessel.require_connection().agent_name), gcs_container_port(int(agent_id)))
    return ports


def build_vessel_job_stack(
    job: JobSpec,
    worker_node: WorkerNodeContext,
    instance: "SimulationInstanceConfig",
    trajectories: "Trajectories",
    geofence: "Geofence",
    *,
    attended: bool = False,
    monitored: bool = False,
    mqtt_connection: Optional["MQttConnectionInfo"] = None,
    service_name: Optional[str] = None,
) -> RunPod:
    """Resolve the instance, write its generated files into the job's folder and assemble the run's pod: its containers and the runner.

    attended: an operator is beside the run, so the stacks that need one are allowed (Mission Planner), and the ground
    control station port of each such vessel's MAVProxy can get a port on the node (RunPod.run, published_ports).

    monitored: the run is judged while it runs, so its runner is a requester of the worker node's monitoring subsystem
    on the cluster's broker.

    mqtt_connection: the broker of a run with a real vessel, when it is not the cluster's (an external one such as
    WARA-PS's). service_name: the name the runner has on that broker. Only an instance with a real vessel talks to a
    broker at all, so only its runner gets the connection.
    """
    from scenegems_tool.messaging.mqtt_client import SERVICE_NAME_VARIABLE, mqtt_container_environment
    from scenegems_tool.subsystems.monitoring.monitoring_types import monitoring_pool_environment
    from scenegems_tool.vessel_stack.registry.catalog import default_resolver
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError, vessel_steering_types
    from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts, write_simulation_gen_files

    try:
        default_resolver().require_instance(instance, attended=attended, steering_types=vessel_steering_types(trajectories.initial_scene.vessels))
    except StackUnavailableError as error:
        raise JobFailed(f"Simulation stack rejected: {error}", retryable=False) from error
    scope = worker_node.job_scope(job)
    gen_folder = f"{scope.folder}/gen"
    pending_writes, stack_compose = build_simulation_docker_stack_artifacts(instance, trajectories, mqtt_connection or worker_node.mqtt_connection, geofence, headless=True, gen_folder=gen_folder)
    write_simulation_gen_files(pending_writes, gen_folder)
    environment = None
    if instance.has_real_vessel:
        environment = {"PYTHONUNBUFFERED": "1", **mqtt_container_environment(mqtt_connection or worker_node.mqtt_connection)}
        if service_name:
            environment[SERVICE_NAME_VARIABLE] = service_name
    if monitored:
        area = worker_node.reference_geofence
        cluster_broker = mqtt_container_environment(worker_node.mqtt_connection)
        environment = {"PYTHONUNBUFFERED": "1"} if environment is None else environment
        environment.update(monitoring_pool_environment(worker_node.pools.service_name(Subsystem.MONITORING), cluster_broker, (area.latitude, area.longitude, area.radius_meters)))
    services = {**stack_compose["services"], RUNNER_SERVICE: runner_service(subsystem_image(Subsystem.SIMULATION), environment=environment)}
    return RunPod(scope, services, cluster=worker_node.cluster, api=worker_node.kubernetes, networks=stack_compose.get("networks"), volumes=stack_compose.get("volumes"))
