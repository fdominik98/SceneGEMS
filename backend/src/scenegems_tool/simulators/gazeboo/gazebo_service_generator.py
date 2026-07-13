from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH, docker_volume_path, runtime_assets_volume_mount


def generate_gazebo_service(world_file: str, vessel_services: list[str], headless: bool = True, display: str = "", verbose: int = 4) -> dict:

    gazebo = {
        "image": "${GAZEBO_IMAGE:-scenegems-gazebo-harmonic:latest}",
        "container_name": "gazebo",
        "hostname": "gazebo",
        "environment": {
            "GZ_HEADLESS": "1" if headless else "0",
            "GZ_VERBOSE": str(verbose),
            "DISPLAY": display,
            "QT_X11_NO_MITSHM": "1",
            "WORLD_SDF": docker_volume_path(world_file),
            "MODELS_DIR": "/models",
        },
        "volumes": [runtime_assets_volume_mount(read_only=True)],
        "entrypoint": [
            "/bin/bash",
            "-c",
            "set -euo pipefail\n" f"tr -d '\\r' < {GAZEBO_ENTRYPOINT_CONTAINER_PATH} > /tmp/entrypoint.sh\n" "chmod +x /tmp/entrypoint.sh\n" "exec /tmp/entrypoint.sh",
        ],
        "ports": ["11345:11345"],
        "networks": ["maritime_net"],
        "depends_on": vessel_services,
    }
    return {"gazebo": gazebo}
