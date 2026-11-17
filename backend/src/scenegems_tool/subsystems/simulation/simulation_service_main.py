"""The container of the simulation subsystem: its pool on the broker (messaging/mqtt_simulation_service.py).

Before it serves, it removes the runs earlier processes of this subsystem left behind on its worker node: a
subsystem whose container was restarted took its workers with it, and their runs' pods stayed, since they are
owned by the subsystem's pod, which is still there (a pod that goes takes its runs with it by itself). Nothing of
them is needed any more, since their tasks failed with the subsystem. A run's pod and its services are found by
the worker node's label and the label of a run (run_pod.run_pod_selector), which nothing else carries, and its
folder by the start of its name.
"""

import logging
import multiprocessing
import os
import shutil
from pathlib import Path
from typing import List, Optional

from scenegems_tool.cluster.worker_node.instance_scope import INSTANCES_FOLDER, InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import Kind, KubernetesApi, KubernetesUnavailable
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import run_pod_selector
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService
from scenegems_tool.subsystems.pool.pool_service_main import serve, service_from_environment
from scenegems_tool.subsystems.simulation.simulation_types import CONTROL_NODE_VARIABLE, KUBERNETES_NAMESPACE_VARIABLE, SIMULATION_SERVICE_NAME, WORKER_NODE_VARIABLE

_logger = logging.getLogger(__name__)


def remove_leftover_stacks(api: Optional[KubernetesApi], control_node_id: str, worker_node_id: str, instances_folder: str = INSTANCES_FOLDER) -> List[str]:
    """Remove the pods, services and folders of the runs an earlier subsystem process left; returns the names of the pods it removed.

    Without a cluster API (api None) only the folders are removed.
    """
    pool = InstanceScope.pooled(control_node_id, worker_node_id, Subsystem.SIMULATION.value)
    removed: List[str] = []
    if api is not None:
        selector = run_pod_selector(worker_node_id)
        try:
            removed = api.delete_labelled(Kind.POD, selector)
            api.delete_labelled(Kind.SERVICE, selector)
        except Exception as error:  # the daemon's removal of its instances finds them later by the same labels
            _logger.warning("Cannot remove the leftover runs of %s: %s", pool.name, error)
        for name in removed:
            _logger.info("Removed the leftover run %s", name)
    prefix = f"{pool.name}-"  # a run's folder is <worker node>-simulation-subsystem-<job>; the pool's own name has no dash after it
    root = Path(instances_folder)
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            if folder.is_dir() and folder.name.startswith(prefix):
                shutil.rmtree(folder, ignore_errors=True)
    return removed


def cluster_api() -> Optional[KubernetesApi]:
    """The cluster API as the subsystem's pod reaches it, in the namespace of its environment; None, with a warning, when there is none."""
    try:
        return KubernetesApi.connect(os.environ[KUBERNETES_NAMESPACE_VARIABLE])
    except (KeyError, KubernetesUnavailable) as error:
        _logger.warning("No cluster API for the simulation subsystem: %s", error)
        return None


def main() -> None:
    remove_leftover_stacks(cluster_api(), os.environ[CONTROL_NODE_VARIABLE], os.environ[WORKER_NODE_VARIABLE])
    serve(service_from_environment(MqttSimulationService, SIMULATION_SERVICE_NAME))


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn")
    main()
