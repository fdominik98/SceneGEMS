import shlex
from typing import Sequence

import numpy as np

from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.messaging.topic_layout import SIMULATION_CONTEXT, SURFACE_DOMAIN, WARAPS_TOPIC_ROOT, parse_unit_topic
from scenegems_tool.vessel_stack.contracts.local_frame import to_true_north
from scenegems_tool.vessel_stack.contracts.stack_services import arduagent_port, gcs_container_port
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER, SITL_CONTAINER
from utils.file_system_utils import SITL_ENTRYPOINT_CONTAINER_PATH, docker_volume_path, runtime_assets_volume_mount

_MAVPROXY_DEFAULT_MODULES = "link,log,signing,wp,rally,fence,ftp,param,relay,tuneopt,arm,mode," "calibration,rc,auxopt,misc,cmdlong,battery,output,layout"
SITL_SERIAL1_BASE_PORT = 5762  # SITL's SERIAL1 (MAVLink) of instance 0; each instance adds 10
GCS_MAVPROXY_RETRY_S = 2  # seconds between MAVProxy starts while SITL boots
ARDUAGENT_RETRY_S = 2  # seconds between ArduAgent starts while its MAVProxy comes up
POSITION_CHANNEL = "/sensor/position"
DEFAULT_SITL_FRAME = "motorboat"  # SITL's boat with a rudder on servo 1 and a throttle on servo 3


def _retried(command: str, retry_s: int) -> list:
    """The command in a shell loop that starts it again when it exits.

    A job's containers have no restart policy (they stop with the job), and a restarted container would get new
    published ports, so the retry is inside the container.
    """
    return ["sh", "-c", f"while true; do {command}; sleep {retry_s}; done"]


def generate_vessel_service(
    mqtt_client: MqttAgentClient,
    params_file: str,
    speed_factor: int,
    is_ardupilot_sim: bool,
    other_position_topics: Sequence[str] = (),
    sitl_frame: str = DEFAULT_SITL_FRAME,
) -> dict:
    """SITL, MAVProxy and ArduAgent of one simulated vessel that ArduAgent drives.

    sitl_frame is the frame SITL starts with (sim_vehicle.py -f), which follows the vessel's steering
    type (ardu_param_generator.sitl_frame): on ardupilot_sim it selects how SITL's boat steers
    (motorboat by a rudder, motorboat-skid by its two motors), so it must match the outputs of the
    parameter file. On gazebo the physics are Gazebo's and the frame only names the default parameters
    sim_vehicle.py loads before the parameter file, which sets every output itself.

    The services are named after the client (the vessel). The agent's name on the broker, and the first level of its
    topics, come from the client's topic when it is a simulated unit's in the WARA-PS layout (messaging/topic_layout.py);
    any other topic leaves the agent the client's name under waraps, as before. other_position_topics are the base
    topics of the instance's other vessels: the agent takes positions from those only, not from every unit on the broker.
    MAVProxy listens on the vessel's gcs_container_port for a ground control station and on its arduagent_port for ArduAgent (stack_services.py: every vessel has ports of its own); the stack that runs the vessel says whether
    that port is published (a job keeps it for a Mission Planner vessel, on a host port Docker assigns).
    """
    mqtt_connection = mqtt_client.mqtt_connection
    mavproxy = f"{mqtt_client.name}_mavproxy"
    arduagent = f"{mqtt_client.name}_arduagent"
    ardupilot = mqtt_client.name

    reference_geofence = mqtt_client.reference_geofence
    vessel_id = int(mqtt_client.actor.id)
    mavproxy_arduagent_port = arduagent_port(vessel_id)
    mavproxy_gcs_port = gcs_container_port(vessel_id)
    sim_port = str(5760 + int(mqtt_client.actor.id) * 10)

    if is_ardupilot_sim:
        lat_long = reference_geofence.to_lat_long(mqtt_client.initial_state.p)
        heading = np.degrees(to_true_north(mqtt_client.initial_state.heading))
        home_pos = f"{lat_long[0]},{lat_long[1]},0,{heading}"
    else:
        home_pos = f"{reference_geofence.latitude},{reference_geofence.longitude},0,0"

    unit = parse_unit_topic(mqtt_client.topic)
    if unit is not None and unit.context != SIMULATION_CONTEXT:
        unit = None  # these services are a simulated vessel's: a topic that says otherwise names nothing here
    agent_env = {
        "NAME": unit.name if unit is not None else f"{mqtt_client.name}",
        "DOMAIN": unit.domain if unit is not None else SURFACE_DOMAIN,
        "REAL_SIM": SIMULATION_CONTEXT,
        "AGENT_DESCRIPTION": "surface vessel",
        "AGENT_MODEL": "vessel.mini_usv",
        "VIDEO_SRC0": "/dev/video0",
        "VIDEO_SERVER": "ome.waraps.org",
        "BROKER": mqtt_connection.agent_broker,
        "PORT": mqtt_connection.port,
        "TLS_CERTIFICE": "0" if not mqtt_connection.tls_connection else "1",
        "MQTT_USER": mqtt_connection.user,
        "MQTT_PASSWORD": mqtt_connection.password,
        "FCS_SERIAL": "/dev/serial0",
        "BAUD_RATE": "57600",
        "CONNECTION_STRING": f"tcp:{mavproxy}:{mavproxy_arduagent_port}",
        "SIM_PORT": sim_port,
        "SPEEDUP": str(speed_factor),
        "VEHICLE": "Rover",
        "MODEL": sitl_frame,
        "VEHICLE_PARAMS": sitl_frame,
        # Bind tcpin on all interfaces inside the mavproxy container; arduagent uses the service hostname.
        "MAVPROXY": f"tcpin:{mavproxy}:{mavproxy_arduagent_port}",
    }
    if unit is not None and unit.root != WARAPS_TOPIC_ROOT:
        agent_env["MQTT_TOPIC_ROOT"] = unit.root
    if other_position_topics:
        agent_env["OTHER_POSITIONS_TOPICS"] = ",".join(f"{topic}{POSITION_CHANNEL}" for topic in other_position_topics)
    env_list = [f"{name}={value}" for name, value in agent_env.items()]
    sitl_env = [
        "SITL_SIMULATOR=ardupilot" if is_ardupilot_sim else "SITL_SIMULATOR=gazebo",
        f"SITL_VEHICLE={agent_env['VEHICLE']}",
        f"SITL_FRAME={agent_env['MODEL']}",
        f"SITL_PARAM_FILE={docker_volume_path(params_file)}",
        "SITL_NO_MAVPROXY=1",
        "SITL_NO_REBUILD=1",
        f"SITL_SPEEDUP={agent_env['SPEEDUP']}",
        f"SITL_CUSTOM_LOCATION={home_pos}",
        f"SITL_SYSID={mqtt_client.actor.id + 1}",
        f"SITL_INSTANCE={mqtt_client.actor.id}",
    ]
    if not is_ardupilot_sim:
        sitl_env.extend(
            [
                "SITL_RESOLVE_HOST=gazebo",
                "SITL_MODEL=JSON",
            ]
        )

    mavproxy_command = [
        "python3",
        "-m",
        "MAVProxy.mavproxy",
        "--non-interactive",
        f"--default-modules={_MAVPROXY_DEFAULT_MODULES}",
        f"--master=tcp:{ardupilot}:{sim_port}",
        f"--out={agent_env['MAVPROXY']}",
        f"--out=tcpin:0.0.0.0:{mavproxy_gcs_port}",
    ]
    docker_services = {
        ardupilot: {
            "image": SITL_CONTAINER.image,
            "restart": "unless-stopped",
            "environment": sitl_env,
            "volumes": [runtime_assets_volume_mount(read_only=True)],
            "entrypoint": [
                "/bin/bash",
                "-c",
                "set -euo pipefail\n" f"tr -d '\\r' < {SITL_ENTRYPOINT_CONTAINER_PATH} > /tmp/sitl_entrypoint.sh\n" "chmod +x /tmp/sitl_entrypoint.sh\n" "exec /tmp/sitl_entrypoint.sh",
            ],
            "extra_hosts": ["host.docker.internal:host-gateway"],
            "networks": ["maritime_net"],
        },
        mavproxy: {
            "image": MAVPROXY_CONTAINER.image,
            "tty": True,
            "stdin_open": True,
            "restart": "unless-stopped",
            "environment": env_list,
            "networks": ["maritime_net"],
            # The ground control station's TCP endpoint, on a host port Docker assigns (a job's stack keeps it only for a Mission Planner vessel)
            "ports": [str(mavproxy_gcs_port)],
            "command": _retried(shlex.join(mavproxy_command), GCS_MAVPROXY_RETRY_S),
        },
        arduagent: {
            "image": ARDUAGENT_CONTAINER.image,
            "depends_on": [mavproxy],
            "restart": "unless-stopped",
            "environment": env_list,
            "networks": ["maritime_net"],
            "command": _retried(ARDUAGENT_CONTAINER.entrypoint, ARDUAGENT_RETRY_S),
        },
    }
    return docker_services


def gcs_mavproxy_service_name(agent_name: str) -> str:
    return f"{agent_name}_mavproxy"


def generate_gcs_mavproxy_service(agent_name: str, vessel_id: int) -> dict:
    """MAVProxy for a Mission Planner vessel (mission_planner_gcs_port): SITL's SERIAL1 to one TCP endpoint for the ground station.

    SERIAL0 stays free for the lockstep runner, which watches the vessel there and whose
    connection is what lets SITL boot. The endpoint's container port is published on a host
    port Docker assigns (no fixed host port, so stacks and vessels never collide); the
    job reads it back and reports it in its status. MAVProxy exits while SITL
    does not listen on SERIAL1 yet (until it has booted), and Docker gives a restarted container
    a new host port, so a shell loop restarts MAVProxy inside the container instead: the port
    the job reported stays the vessel's for the whole run.
    """
    mavproxy = [
        "python3",
        "-m",
        "MAVProxy.mavproxy",
        "--non-interactive",
        f"--default-modules={_MAVPROXY_DEFAULT_MODULES}",
        f"--master=tcp:{agent_name}:{SITL_SERIAL1_BASE_PORT + 10 * int(vessel_id)}",
        f"--out=tcpin:0.0.0.0:{gcs_container_port(vessel_id)}",
    ]
    return {
        gcs_mavproxy_service_name(agent_name): {
            "image": MAVPROXY_CONTAINER.image,
            "tty": True,
            "stdin_open": True,
            "restart": "unless-stopped",
            "networks": ["maritime_net"],
            "ports": [str(gcs_container_port(vessel_id))],
            "command": _retried(shlex.join(mavproxy), GCS_MAVPROXY_RETRY_S),
        }
    }
