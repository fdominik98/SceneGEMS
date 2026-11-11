"""ArduPilot control layer adapter: SITL with its parameter file per vessel, plus MAVProxy and ArduAgent for ArduAgent-driven vessels."""

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_GCS_PORT
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardu_param_generator import generate_ardu_params
from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import ARDUAGENT_ADAPTER_IDS, arduagent_control_mode
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUPILOT_CONTROL_LAYER
from scenegems_tool.vessel_stack.control_layers.ardupilot.vessel_service_generator import generate_gcs_mavproxy_service, generate_vessel_service
from scenegems_tool.vessel_stack.registry.catalog import default_resolver


class ArduPilotControlLayer:
    spec = ARDUPILOT_CONTROL_LAYER

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        connection = vessel_config.require_connection()
        asv_adapter = default_resolver().resolve(vessel_config.stack, vessel_config.adapter_ids).asv_adapter
        arduagent = asv_adapter is not None and asv_adapter.id in ARDUAGENT_ADAPTER_IDS
        # The service generator reads the agent's name, broker and home pose from a client
        # object; it is never connected. Only ArduAgent reads a control mode, and only ArduAgent
        # vessels have one (USV Navigation has none).
        agent_stub = MqttAgentClient(
            vessel=vessel,
            mqtt_connection=request.mqtt_connection,
            topic=connection.topic,
            control_mode=arduagent_control_mode(vessel_config.stack.asv_system) if arduagent else "",
            agent_name=connection.agent_name,
            reference_geofence=request.reference_geofence,
            initial_state=state,
            parent_service_name="simulation_service",
            mission_waypoints=[],
        )

        environment = request.simulation.environment
        ardu_params = generate_ardu_params(
            vessel,
            request.trajectories.get_max_speed(vessel),
            environment.wind_vector,
            environment.wave,
            vessel_config.stack.simulation_layer,
            guided_targets=not arduagent,
        )
        params_file = f"{request.gen_folder}/params-{connection.agent_name}.params"
        lines = []
        for key, value in ardu_params.items():
            if value is not None:
                lines.append(f"{key}\t{value}\n")
        artifacts.pending_writes.append((params_file, "".join(lines)))

        # sitl_internal_physics homes SITL at the start pose; ardupilot_gazebo_plugin runs SITL's JSON backend against Gazebo.
        sitl_internal_physics = vessel_config.stack.simulation_layer == SimulationLayerId.ARDUPILOT_SIM
        services = generate_vessel_service(agent_stub, connection.port, params_file, request.simulation.speedup, sitl_internal_physics)
        if not arduagent:
            # The ASV system talks MAVLink to SITL's SERIAL0 itself (mavlink_link.py), so the
            # vessel gets SITL only: no MAVProxy and no ArduAgent. A Mission Planner vessel adds
            # MAVProxy with the operator's ground control station endpoint.
            services = {connection.agent_name: services[connection.agent_name]}
            if asv_adapter is not None and asv_adapter.id == MISSION_PLANNER_GCS_PORT.id:
                services.update(generate_gcs_mavproxy_service(connection.agent_name, vessel.id))
        artifacts.services.update(services)
