"""Force-remove Docker subsystem containers started by the SceneGEMS backend.

These are the workbench's containers: the stacks of its live sessions and its monitors. Scoped
instances of a node belong to its NodeContext, which removes them in `shutdown`.
"""

from __future__ import annotations

import logging
import threading

from scenegems_tool.cluster.node.launchers.docker_cli import container_ids_for_compose_project_prefix, force_remove_containers

_logger = logging.getLogger(__name__)

_shutdown_lock = threading.Lock()
_shutdown_done = False


def force_destroy_monitor_subsystem_stack() -> None:
    """Fast teardown: force-remove every COLREGS monitoring worker container of the workbench."""
    from scenegems_tool.cluster.node.launchers.pooled.monitor_service import WORKBENCH_COMPOSE_PROJECT_PREFIX

    force_remove_containers(container_ids_for_compose_project_prefix(WORKBENCH_COMPOSE_PROJECT_PREFIX))


def shutdown_all_docker_subsystems() -> None:
    """Tear down subsystem containers on backend process exit."""
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    try:
        from scenegems_tool.cluster.node.launchers.per_job.simulation_session_stack import force_destroy_session_stacks

        force_destroy_session_stacks()
        force_destroy_monitor_subsystem_stack()
    except BaseException:
        _logger.exception("Docker subsystem shutdown failed")
