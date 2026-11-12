from typing import Optional

from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER
from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH, docker_volume_path, runtime_assets_volume_mount


def generate_gazebo_service(world_file: str, vessel_services: list[str], headless: bool = True, display: str = "", verbose: int = 4, actuator_port: Optional[int] = None) -> dict:
    """The Gazebo service. actuator_port: the world starts paused and the gz-transport actuator listens on that port
    (custom control layer), instead of the world running on its own.

    No container name and no host port: SITL and the lockstep runners reach it as `gazebo` on the
    stack's network, and the stack that runs it names its containers (one per job).
    """
    gazebo = {
        "image": GAZEBO_CONTAINER.image,
        "hostname": "gazebo",
        "environment": {
            "GZ_HEADLESS": "1" if headless else "0",
            "GZ_VERBOSE": str(verbose),
            "DISPLAY": display,
            "QT_X11_NO_MITSHM": "1",
            "WORLD_SDF": docker_volume_path(world_file),
        },
        "volumes": [runtime_assets_volume_mount(read_only=True)],
        "entrypoint": [
            "/bin/bash",
            "-c",
            "set -euo pipefail\n" f"tr -d '\\r' < {GAZEBO_ENTRYPOINT_CONTAINER_PATH} > /tmp/entrypoint.sh\n" "chmod +x /tmp/entrypoint.sh\n" "exec /tmp/entrypoint.sh",
        ],
        "networks": ["maritime_net"],
        "depends_on": vessel_services,
    }
    if actuator_port is not None:
        gazebo["environment"]["GZ_START_PAUSED"] = "1"
        gazebo["environment"]["GZ_ACTUATOR_PORT"] = str(actuator_port)
    if not vessel_services:
        del gazebo["depends_on"]
    return {"gazebo": gazebo}
