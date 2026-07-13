import os
from typing import Any, Dict

SCENEGEMS_BROKER_NETWORK_KEY = "scenegems_broker"


def scenegems_broker_network_name() -> str:
    default = "scenegems_default"
    configured = os.environ.get("SCENEGEMS_DOCKER_NETWORK", default).strip()
    return configured or default


def scenegems_broker_network_definition() -> Dict[str, Dict[str, Any]]:
    return {
        SCENEGEMS_BROKER_NETWORK_KEY: {
            "external": True,
            "name": scenegems_broker_network_name(),
        }
    }


def attach_broker_network_to_service(service: dict) -> None:
    networks = list(service.get("networks", []))
    if SCENEGEMS_BROKER_NETWORK_KEY not in networks:
        networks.append(SCENEGEMS_BROKER_NETWORK_KEY)
    service["networks"] = networks


def attach_broker_network_to_compose(compose: dict) -> dict:
    compose.setdefault("networks", {}).update(scenegems_broker_network_definition())
    for service in compose.get("services", {}).values():
        attach_broker_network_to_service(service)
    return compose
