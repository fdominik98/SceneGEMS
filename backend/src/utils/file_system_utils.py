import os
from pathlib import Path
from typing import Dict, List

_BACKEND_SRC_UTILS = os.path.dirname(os.path.abspath(__file__))
BACKEND_ROOT = os.path.normpath(f"{_BACKEND_SRC_UTILS}/../..")
REPO_ROOT = os.path.normpath(f"{BACKEND_ROOT}/..")
# Repo root: Docker build context for subsystem images at monitoring/, scenario_generation/, etc.
ROOT_FOLDER = REPO_ROOT

ASSET_FOLDER = f"{BACKEND_ROOT}/assets"
GEN_DATA_FOLDER = f"{ASSET_FOLDER}/gen_data"
FUNCTIONAL_MODELS_FOLDER = f"{ASSET_FOLDER}/generated_functional_models"
PROJECT_REPORT_FOLDER = f"{ASSET_FOLDER}/project_report"
IMAGES_FOLDER = f"{ASSET_FOLDER}/images"
EXPORTED_PLOTS_FOLDER = f"{IMAGES_FOLDER}/exported_plots"
GAZEBO_FOLDER = f"{REPO_ROOT}/gazebo"
SITL_FOLDER = f"{REPO_ROOT}/sitl"
MAVPROXY_FOLDER = f"{REPO_ROOT}/mavproxy"
MONITORING_FOLDER = f"{REPO_ROOT}/monitoring"
SCENARIO_GENERATION_FOLDER = f"{REPO_ROOT}/scenario_generation"
SCENARIO_EXECUTION_FOLDER = f"{REPO_ROOT}/scenario_execution"
RUNTIME_ASSETS_FOLDER = f"{ASSET_FOLDER}/runtime_assets"
MONITORING_GEN_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/monitoring/gen_tmp"
SCENARIO_EXECUTION_GEN_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/scenario_execution/gen_tmp"
SCENARIO_GENERATION_RUNTIME_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/scenario_generation"
SCENARIO_GENERATION_GEN_FOLDER = f"{SCENARIO_GENERATION_RUNTIME_FOLDER}/gen_tmp"
SCENIC_FOLDER = SCENARIO_GENERATION_RUNTIME_FOLDER
SIMULATION_GEN_FOLDER = SCENARIO_EXECUTION_GEN_FOLDER
SIMULATION_GZ_FOLDER = GAZEBO_FOLDER
SSH_KEY_FILE = f"{ASSET_FOLDER}/ssh_key/measurement_key.pem"
CONFIG_FOLDER = f"{ASSET_FOLDER}/domain_config"
COLREGS_CONSTANTS_FOLDER = f"{CONFIG_FOLDER}/colregs_constants"
VESSEL_TYPES_FOLDER = f"{CONFIG_FOLDER}/vessel_types"
STATIC_OBSTACLE_TYPES_FOLDER = f"{CONFIG_FOLDER}/static_obstacle_types"

RUNTIME_ASSETS_VOLUME = os.environ.get("SCENEGEMS_RUNTIME_VOLUME", "scenegems_runtime_assets")
GAZEBO_GEN_MOUNT = f"{RUNTIME_ASSETS_FOLDER}/scenario_execution/gen_tmp"
SITL_ENTRYPOINT_CONTAINER_PATH = "/scripts/sitl_entrypoint.sh"
GAZEBO_ENTRYPOINT_CONTAINER_PATH = "/scripts/entrypoint.sh"
GAZEBO_MODELS_CONTAINER_PATH = "/models"

_initialized = False  # Global flag


def ensure_directories() -> None:
    global _initialized
    if _initialized:
        return

    runtime_assets_writable = os.access(RUNTIME_ASSETS_FOLDER, os.W_OK)

    folders = [
        ASSET_FOLDER,
        GEN_DATA_FOLDER,
        FUNCTIONAL_MODELS_FOLDER,
        PROJECT_REPORT_FOLDER,
        IMAGES_FOLDER,
        EXPORTED_PLOTS_FOLDER,
        COLREGS_CONSTANTS_FOLDER,
        VESSEL_TYPES_FOLDER,
        STATIC_OBSTACLE_TYPES_FOLDER,
        CONFIG_FOLDER,
    ]
    if runtime_assets_writable:
        folders.extend(
            [
                RUNTIME_ASSETS_FOLDER,
                SCENARIO_GENERATION_RUNTIME_FOLDER,
                MONITORING_GEN_FOLDER,
                SCENARIO_GENERATION_GEN_FOLDER,
                SCENARIO_EXECUTION_GEN_FOLDER,
            ]
        )

    for folder in folders:
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            if error.errno == 30:  # EROFS — read-only mount (e.g. subsystem containers)
                continue
            raise

    _initialized = True


def runtime_assets_volume_mount(*, read_only: bool = False) -> str:
    suffix = ":ro" if read_only else ""
    return f"{RUNTIME_ASSETS_VOLUME}:{RUNTIME_ASSETS_FOLDER}{suffix}"


def path_in_runtime_assets(local_path: str) -> str:
    normalized = os.path.normpath(local_path)
    runtime_root = os.path.normpath(RUNTIME_ASSETS_FOLDER)
    try:
        rel = os.path.relpath(normalized, runtime_root)
    except ValueError:
        return normalized.replace("\\", "/")
    if rel.startswith(".."):
        return normalized.replace("\\", "/")
    return f"{RUNTIME_ASSETS_FOLDER}/{rel}".replace("\\", "/")


def compose_external_volumes() -> dict:
    return {RUNTIME_ASSETS_VOLUME: {"external": True}}


def merge_compose_volumes(compose: dict) -> dict:
    compose["volumes"] = {**compose.get("volumes", {}), **compose_external_volumes()}
    return compose


def docker_volume_path(local_path: str) -> str:
    """Return the in-container path for files on the shared runtime assets volume."""
    return path_in_runtime_assets(local_path)


def get_all_file_paths(directory, extensions: List[str]) -> Dict[str, List[str]]:
    if not os.path.isdir(directory):
        raise ValueError("The path is not a directory or invalid.")
    path_by_extension: Dict[str, List[str]] = {ext: [] for ext in extensions}
    for root, _, files in os.walk(directory):
        for file in files:
            for ext in extensions:
                if file.endswith(ext):
                    path_by_extension[ext].append(os.path.join(root, file))
                    break
    return path_by_extension
