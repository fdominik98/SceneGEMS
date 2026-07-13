import numpy as np

from scenegems_tool.waraps_integration.mqtt_agent_client import MqttAgentClient
from scenegems_tool.waraps_integration.sim_utils import to_true_north
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
            "image": "${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}",
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
            "image": "${MAVPROXY_IMAGE:-scenegems-mavproxy:latest}",
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
            "image": "${ARDUAGENT_IMAGE:-scenegems-arduagent:latest}",
            "depends_on": [mavproxy],
            "restart": "unless-stopped",
            "environment": env_list,
            "networks": ["maritime_net"],
            "command": "python -B -u /app/main.py",
        },
    }
    return docker_services
