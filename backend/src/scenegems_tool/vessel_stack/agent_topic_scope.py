"""Which topic prefix the vessel agents of an instance use: the live session's, or none.

A live session on the control node's broker has a topic prefix (gateway/socket_session.py), and the
session's own clients (the gateway's, the simulation service, the monitor) use it. Its
vessel agents use it only when every vessel is simulated: then the instance's ArduAgents, run
by the session, publish and subscribe under it (deploy/images/arduagent/app/agent_topics.py).
A real vessel's on-board ArduAgent publishes the unscoped WARA-PS topics, so the clients of an
instance with a real vessel, and its simulated ArduAgents (which watch the other agents'
positions), keep the unscoped topics.
"""

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig


def instance_has_real_vessel(simulation_config: SimulationInstanceConfig) -> bool:
    return any(not vessel.is_simulated for vessel in simulation_config.vessels.values())


def agent_mqtt_connection(mqtt_connection: MQttConnectionInfo, simulation_config: SimulationInstanceConfig) -> MQttConnectionInfo:
    """The connection of the instance's vessel agents and of the clients that talk to them."""
    if instance_has_real_vessel(simulation_config) and mqtt_connection.topic_prefix:
        return mqtt_connection.with_topic_prefix("")
    return mqtt_connection
