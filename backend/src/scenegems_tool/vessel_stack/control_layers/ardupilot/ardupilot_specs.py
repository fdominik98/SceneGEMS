"""Specs of the ArduPilot control layer: per vessel SITL, MAVProxy and ArduAgent."""

from scenegems_tool.vessel_stack.contracts.adapter_spec import UPSTREAM_PINS_FILE, ContainerSpec, LayerSpec, image_reference
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef
from utils.file_system_utils import SITL_ENTRYPOINT_CONTAINER_PATH

SITL_CONTAINER = ContainerSpec(
    image=image_reference("SITL_IMAGE", "scenegems-ardupilot-sitl"),
    build_fingerprint_source="deploy/images/sitl",
    entrypoint=SITL_ENTRYPOINT_CONTAINER_PATH,
    upstream_pins_file=UPSTREAM_PINS_FILE,
)
MAVPROXY_CONTAINER = ContainerSpec(
    image=image_reference("MAVPROXY_IMAGE", "scenegems-mavproxy"),
    build_fingerprint_source="deploy/images/mavproxy",
    entrypoint="python3 -m MAVProxy.mavproxy",
)
ARDUAGENT_CONTAINER = ContainerSpec(
    image=image_reference("ARDUAGENT_IMAGE", "scenegems-arduagent"),
    build_fingerprint_source="deploy/images/arduagent",
    entrypoint="python -B -u /app/main.py",
)

ARDUPILOT_CONTROL_LAYER = LayerSpec(
    layer=LayerRef.of(ControlLayerId.ARDUPILOT),
    description="ArduPilot Rover SITL as the low-level controller. Every vessel gets SITL with a generated parameter file; vessels driven through ArduAgent also get MAVProxy and ArduAgent.",
    provides_ports=frozenset({Port.MAVLINK, Port.ACTUATOR_CMD}),
    requires_ports=frozenset({Port.MAVLINK, Port.WAYPOINT_MISSION, Port.ENVIRONMENT}),
    # MAVProxy and ArduAgent are listed on the ASV-side adapters that start them (ArduPilotControlLayer.add_vessel).
    containers=(SITL_CONTAINER,),
)
