import shlex

import numpy as np

from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.vessel_stack.asv_software.mission_planner.mission_planner_specs import GCS_CONTAINER_PORT
from scenegems_tool.vessel_stack.contracts.local_frame import to_true_north
from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import ARDUAGENT_CONTAINER, MAVPROXY_CONTAINER, SITL_CONTAINER
from utils.file_system_utils import SITL_ENTRYPOINT_CONTAINER_PATH, docker_volume_path, runtime_assets_volume_mount

_MAVPROXY_DEFAULT_MODULES = "link,log,signing,wp,rally,fence,ftp,param,relay,tuneopt,arm,mode," "calibration,rc,auxopt,misc,cmdlong,battery,output,layout"


def generate_vessel_service(
    mqtt_client: MqttAgentClient,
    port: int,
    params_file: str,
    speed_factor: int,
    is_ardupilot_sim: bool,
) -> dict:
    mqtt_connection = mqtt_client.mqtt_connection
    mavproxy = f"{mqtt_client.name}_mavproxy"
    arduagent = f"{mqtt_client.name}_arduagent"
    ardupilot = mqtt_client.name

    reference_geofence = mqtt_client.reference_geofence
    arduagent_port = 14551
    sim_port = str(5760 + int(mqtt_client.actor.id) * 10)

    if is_ardupilot_sim:
        lat_long = reference_geofence.to_lat_long(mqtt_client.initial_state.p)
        heading = np.degrees(to_true_north(mqtt_client.initial_state.heading))
        home_pos = f"{lat_long[0]},{lat_long[1]},0,{heading}"
    else:
        home_pos = f"{reference_geofence.latitude},{reference_geofence.longitude},0,0"

    agent_env = {
        "NAME": f"{mqtt_client.name}",
        "DOMAIN": "surface",
        "REAL_SIM": "simulation",
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
        "CONNECTION_STRING": f"tcp:{mavproxy}:{arduagent_port}",
        "SIM_PORT": sim_port,
        "SPEEDUP": str(speed_factor),
        "VEHICLE": "Rover",
        "MODEL": "motorboat",  # or rover-skid
        "VEHICLE_PARAMS": "motorboat",
        # Bind tcpin on all interfaces inside the mavproxy container; arduagent uses the service hostname.
        "MAVPROXY": f"tcpin:{mavproxy}:{arduagent_port}",
        "LOCAL_BRIDGE": "udp:host.docker.internal:14550",
        "GCS_1": f"udp:host.docker.internal:{str(port)}",
    }
    if mqtt_connection.topic_prefix:
        # A scoped ArduAgent publishes and subscribes under the live session's prefix (agent_topics.py in its image).
        agent_env["MQTT_TOPIC_PREFIX"] = mqtt_connection.topic_prefix
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
            # "ports": [f"{port}:{port}/udp"],
            "command": [
                "python3",
                "-m",
                "MAVProxy.mavproxy",
                f"--default-modules={_MAVPROXY_DEFAULT_MODULES}",
                f"--master=tcp:{ardupilot}:{sim_port}",
                f"--out={agent_env['MAVPROXY']}",
                f"--out={agent_env['GCS_1']}",
            ],
        },
        arduagent: {
            "image": ARDUAGENT_CONTAINER.image,
            "depends_on": [mavproxy],
            "restart": "unless-stopped",
            "environment": env_list,
            "networks": ["maritime_net"],
            "command": ARDUAGENT_CONTAINER.entrypoint,
        },
    }
    return docker_services


SITL_SERIAL1_BASE_PORT = 5762  # SITL's SERIAL1 (MAVLink) of instance 0; each instance adds 10
GCS_MAVPROXY_RETRY_S = 2  # seconds between MAVProxy starts while SITL boots


def gcs_mavproxy_service_name(agent_name: str) -> str:
    return f"{agent_name}_mavproxy"


def generate_gcs_mavproxy_service(agent_name: str, vessel_id: int) -> dict:
    """MAVProxy for a Mission Planner vessel (mission_planner_gcs_port): SITL's SERIAL1 to one TCP endpoint for the ground station.

    SERIAL0 stays free for the lockstep runner, which watches the vessel there and whose
    connection is what lets SITL boot. The endpoint's container port is published on a host
    port Docker assigns (no fixed host port, so stacks and vessels never collide); the
    session reads it back and reports it in the simulation status. MAVProxy exits while SITL
    does not listen on SERIAL1 yet (until it has booted), and Docker gives a restarted container
    a new host port, so a shell loop restarts MAVProxy inside the container instead: the port
    the session reported stays the vessel's for the whole run.
    """
    mavproxy = [
        "python3",
        "-m",
        "MAVProxy.mavproxy",
        "--non-interactive",
        f"--default-modules={_MAVPROXY_DEFAULT_MODULES}",
        f"--master=tcp:{agent_name}:{SITL_SERIAL1_BASE_PORT + 10 * int(vessel_id)}",
        f"--out=tcpin:0.0.0.0:{GCS_CONTAINER_PORT}",
    ]
    return {
        gcs_mavproxy_service_name(agent_name): {
            "image": MAVPROXY_CONTAINER.image,
            "tty": True,
            "stdin_open": True,
            "restart": "unless-stopped",
            "networks": ["maritime_net"],
            "ports": [str(GCS_CONTAINER_PORT)],
            "command": ["sh", "-c", f"while true; do {shlex.join(mavproxy)}; sleep {GCS_MAVPROXY_RETRY_S}; done"],
        }
    }
