"""Force-remove Docker subsystem containers started by the SceneGEMS backend."""

from __future__ import annotations

import logging
import subprocess
import threading

_logger = logging.getLogger(__name__)

_MQTT_BROKER_COMPOSE_PROJECT = "mqtt_broker"
_MQTT_BROKER_CONTAINER_NAME = "local_broker"
_SCENARIO_GENERATION_COMPOSE_PROJECT = "scenegems-scenario-generation-subsystem"

_shutdown_lock = threading.Lock()
_shutdown_done = False


def _container_ids_for_compose_project(project: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def _container_ids_by_name(container_name: str) -> list[str]:
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name=^{container_name}$"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [container_id for container_id in result.stdout.split() if container_id]


def _force_remove_container_ids(container_ids: list[str]) -> None:
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False)


def force_destroy_mqtt_broker() -> None:
    """Stop the local MQTT broker container started via mqtt_broker/docker-compose.yml."""
    container_ids = _container_ids_for_compose_project(_MQTT_BROKER_COMPOSE_PROJECT)
    if not container_ids:
        container_ids = _container_ids_by_name(_MQTT_BROKER_CONTAINER_NAME)
    _force_remove_container_ids(container_ids)


def force_destroy_scenario_generation_stack() -> None:
    """Fast teardown: force-remove scenario-generation subsystem containers."""
    _force_remove_container_ids(_container_ids_for_compose_project(_SCENARIO_GENERATION_COMPOSE_PROJECT))


def shutdown_all_docker_subsystems() -> None:
    """Tear down subsystem containers on backend process exit."""
    global _shutdown_done
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    try:
        from scenegems_tool.monitoring.monitor_subsystem_container import (
            force_destroy_monitor_subsystem_stack,
        )
        from scenegems_tool.scenario_generation.scenario_generation_container import (
            force_destroy_scenario_generation_stack,
        )
        from scenegems_tool.simulators.scenegems-scenario-execution-subsystem_container import (
            force_destroy_scenario_execution_stack,
        )

        force_destroy_scenario_execution_stack()
        force_destroy_scenario_generation_stack()
        force_destroy_monitor_subsystem_stack()
    except BaseException:
        _logger.exception("Docker subsystem shutdown failed")
