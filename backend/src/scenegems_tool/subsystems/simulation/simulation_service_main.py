"""The container of the simulation subsystem: its pool on the broker (messaging/mqtt_simulation_service.py).

Before it serves, it removes the vessel stacks earlier tasks of this worker node left behind: a subsystem that
was stopped or died took its workers with it, and their stacks stayed. Nothing of them is needed any more, since
their tasks failed with the subsystem. A stack is found by the start of its containers' names, which every task's
containers share and nothing else on the worker node has.
"""

import logging
import multiprocessing
import os
import shutil
from pathlib import Path
from typing import List

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCES_FOLDER, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.docker_cli import force_remove_instance, instance_keys_with_name_prefix, remove_instance_networks
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment
from scenegems_tool.subsystems.simulation.simulation_types import CONTROL_NODE_VARIABLE, SIMULATION_SERVICE_NAME, WORKER_NODE_VARIABLE

_logger = logging.getLogger(__name__)


def remove_leftover_stacks(control_node_id: str, worker_node_id: str, instances_folder: str = INSTANCES_FOLDER) -> List[str]:
    """Remove the containers, networks and folders of the task stacks an earlier subsystem process left; returns the instances it removed."""
    pool = InstanceScope.pooled(control_node_id, worker_node_id, Subsystem.SIMULATION.value)
    prefix = f"{pool.docker_name}-"  # the subsystem's own container is named exactly pool.docker_name
    try:
        keys = instance_keys_with_name_prefix(pool.compose_project, prefix)
    except OSError as error:  # no Docker CLI: nothing was started from here
        _logger.warning("Cannot look for leftover stacks of %s: %s", pool.docker_name, error)
        keys = []
    for key in keys:
        _logger.info("Removing the leftover stack of instance %s", key)
        force_remove_instance(pool.compose_project, key)
        remove_instance_networks(pool.compose_project, key)
    root = Path(instances_folder)
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and folder.name.startswith(prefix):
                shutil.rmtree(folder, ignore_errors=True)
    return keys


def main() -> None:
    remove_leftover_stacks(os.environ[CONTROL_NODE_VARIABLE], os.environ[WORKER_NODE_VARIABLE])
    serve(service_from_environment(MqttSimulationService, SIMULATION_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
