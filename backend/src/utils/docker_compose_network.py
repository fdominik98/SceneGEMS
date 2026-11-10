import os
from typing import Any, Dict, Optional

SCENEGEMS_BROKER_NETWORK_KEY = "scenegems_broker"


def scenegems_broker_network_name() -> str:
    default = "scenegems_default"
    configured = os.environ.get("SCENEGEMS_DOCKER_NETWORK", default).strip()
    return configured or default


def scenegems_broker_network_definition(network_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    return {
        SCENEGEMS_BROKER_NETWORK_KEY: {
            "external": True,
            "name": network_name or scenegems_broker_network_name(),
        }
    }


def attach_broker_network_to_service(service: dict) -> None:
    networks = list(service.get("networks", []))
    if SCENEGEMS_BROKER_NETWORK_KEY not in networks:
        networks.append(SCENEGEMS_BROKER_NETWORK_KEY)
    service["networks"] = networks


def attach_broker_network_to_compose(compose: dict, network_name: Optional[str] = None) -> dict:
    """Attach every service to the external network of the broker (the worker node's network when one is named)."""
    compose.setdefault("networks", {}).update(scenegems_broker_network_definition(network_name))
    for service in compose.get("services", {}).values():
        attach_broker_network_to_service(service)
    return compose
