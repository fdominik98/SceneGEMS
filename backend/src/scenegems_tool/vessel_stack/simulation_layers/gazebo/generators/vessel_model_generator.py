"""SDF of one generated vessel: a parametric ship hull (vessel_dynamics.py, hull_form.py) with the vessel's steering gear.

The hull floats on boxes that follow its shape and shows its surface as a mesh, a file of its own
next to the model (generate_hull_mesh, hull_mesh_filename).

Steering gear, by the vessel's steering type:

- skid: thrusters motor_port and motor_stbd, steered by their thrust difference.
- rudder: thruster motor_center and a rudder (steering_link) on steering_joint behind it.
- vectored_thrust: thruster motor_center on a mount (steering_link) that turns on steering_joint.

A helm angle on steering_joint is counterclockwise seen from above: positive turns the vessel to
starboard. A JointPositionController moves the joint to the commanded angle at the helm's speed.

Control layer variants:

- ardupilot: the ArduPilotPlugin turns SITL servo outputs into commands (JSON lockstep backend)
  and reads the IMU. Skid: servo 1 the port thrust, servo 3 the starboard thrust. Rudder and
  vectored thrust: servo 1 the helm angle, servo 3 the thrust.
- custom: no ArduPilotPlugin. A controller publishes gz.msgs.Double thrust in N on
  /model/<name>/joint/motor_<which>_joint/cmd_thrust and the helm angle in rad on
  /model/<name>/joint/steering_joint/cmd_pos, and reads gz.msgs.Odometry on /model/<name>/odometry.
"""

import math
from typing import Mapping, Optional, Tuple

import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import wave_forces_enabled
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hull_form import HullStation
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import rudder_normal_force_coefficient
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import ardupilot_steering_multiplier, ardupilot_thrust_multiplier
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import BUOYANCY_GRID, HULL_STATIONS, VesselDynamics, derive_vessel_dynamics, hull_stations
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides

GAZEBO_MODEL_CONTROL_LAYERS = (ControlLayerId.ARDUPILOT, ControlLayerId.CUSTOM)
ODOMETRY_RATE_HZ = 50
# Under waves the wave-aware buoyancy reads the wave height at the corners of each collision box's
# faces, so a box as long as a wave sees a flat sea. Cells of at most 1/WAVE_CELLS_PER_WAVELENGTH of
# the wavelength let the hull heave and pitch with the wave (the WP2 spike's 3 by 3 cells were too
# coarse for the 30 and 100 m hulls in 5 s waves), up to MAX_WAVE_CELLS per side to bound the cost.
WAVE_CELLS_PER_WAVELENGTH = 8
MAX_WAVE_CELLS = 24
GRAVITY = 9.81
STEERING_JOINT = "steering_joint"
STEERING_LINK = "steering_link"
STEERING_STOP_MARGIN = math.radians(5.0)  # the helm joint's stops lie this far beyond hard over, the largest angle commanded
RUDDER_THICKNESS_SHARE = 0.15  # blade thickness over its chord, for the model's look and inertia only


def hull_mesh_filename(agent_name: str) -> str:
    """The hull surface of a vessel's model, a file next to the model it is referenced from."""
    return f"{agent_name}_hull.stl"


def thruster_names(steering_type: str) -> Tuple[str, ...]:
    """Thrusters of a model in the order their thrusts are commanded: the links are motor_<name>_link, the joints motor_<name>_joint."""
    return ("port", "stbd") if steering_type == SteeringType.SKID.value else ("center",)


def thrust_topic(agent_name: str, thruster: str) -> str:
    return f"/model/{agent_name}/joint/motor_{thruster}_joint/cmd_thrust"


def steering_topic(agent_name: str) -> str:
    """gz.msgs.Double helm angle in rad of a model with a rudder or vectored thrust."""
    return f"/model/{agent_name}/joint/{STEERING_JOINT}/cmd_pos"


def _f(value: float) -> str:
    """Plain decimal with up to 6 significant digits (no exponent, which keeps the SDF readable)."""
    return np.format_float_positional(float(value), precision=6, unique=False, fractional=False, trim="-")


def sdf_value(value: float) -> float:
    """The value Gazebo reads back from the SDF: rounded as _f writes it."""
    return float(_f(value))


def _inertia(ixx: float, iyy: float, izz: float) -> str:
    return f"<ixx>{_f(ixx)}</ixx><iyy>{_f(iyy)}</iyy><izz>{_f(izz)}</izz><ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>"


def generate_vessel_model(
    vessel: ConcreteVessel,
    agent_name: str,
    control_layer: ControlLayerId = ControlLayerId.ARDUPILOT,
    environment: Optional[EnvironmentConfig] = None,
    overrides: Optional[Mapping[str, float]] = None,
) -> str:
    """Model of one vessel. The environment sets the windage linearization and whether the hull carries
    the wave-aware buoyancy; overrides default to the vessel_dynamics files' entries for this vessel."""
    if overrides is None:
        overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
    wind_speed = float(np.linalg.norm(environment.wind_vector)) if environment is not None else 0.0
    dynamics = derive_vessel_dynamics(vessel, wind_speed, overrides)
    wave = environment.wave if wave_forces_enabled(environment) else None
    return render_vessel_model(dynamics, agent_name, int(vessel.id), control_layer, wave)


def generate_hull_mesh(vessel: ConcreteVessel, agent_name: str, overrides: Optional[Mapping[str, float]] = None) -> str:
    """The hull surface of the vessel's model as ASCII STL, in the model's frame (origin at the waterline over the hull's center of buoyancy)."""
    if overrides is None:
        overrides = load_vessel_dynamics_overrides().for_vessel(vessel)
    dynamics = derive_vessel_dynamics(vessel, 0.0, overrides)
    return dynamics.hull.mesh(dynamics.height).moved(dynamics.hull_x).to_stl(f"{agent_name}_hull")


def deep_water_wavelength(period: float) -> float:
    return GRAVITY * period**2 / (2.0 * math.pi)


def buoyancy_cells(d: VesselDynamics, wave: Optional[WaveConfig] = None) -> Tuple[int, int]:
    """Buoyancy cells along and across the hull: HULL_STATIONS by BUOYANCY_GRID in flat water, finer under waves."""
    if wave is None:
        return HULL_STATIONS, BUOYANCY_GRID
    cell = deep_water_wavelength(wave.period) / WAVE_CELLS_PER_WAVELENGTH

    def count(extent: float, least: int) -> int:
        return int(min(max(math.ceil(extent / cell), least), max(MAX_WAVE_CELLS, least)))

    return count(d.length, HULL_STATIONS), count(d.breadth, BUOYANCY_GRID)


def buoyancy_stations(d: VesselDynamics, wave: Optional[WaveConfig] = None) -> Tuple[HullStation, ...]:
    """The buoyant boxes along the hull: the dynamics' own in flat water, the same hull cut finer under waves."""
    cells_along, _ = buoyancy_cells(d, wave)
    return d.stations if cells_along == len(d.stations) else hull_stations(d.hull, cells_along)[0]


def render_vessel_model(d: VesselDynamics, agent_name: str, vessel_id: int, control_layer: ControlLayerId, wave: Optional[WaveConfig] = None) -> str:
    """wave: the wave field the hull floats in (wave forces on), None for flat water."""
    if control_layer not in GAZEBO_MODEL_CONTROL_LAYERS:
        raise ValueError(f"No Gazebo vessel model for control layer {control_layer.value}; supported: {[layer.value for layer in GAZEBO_MODEL_CONTROL_LAYERS]}")
    ardupilot = control_layer == ControlLayerId.ARDUPILOT
    freeboard = d.height - d.draft
    thruster_radius = d.propeller_diameter / 2.0
    thruster_ixx = 0.5 * d.thruster_mass * thruster_radius**2
    thruster_iyy = d.thruster_mass / 12.0 * (3.0 * thruster_radius**2 + d.motor_length**2)
    windage_ixx = d.windage_mass / 12.0 * (d.breadth**2 + freeboard**2)
    windage_iyy = d.windage_mass / 12.0 * (d.length**2 + freeboard**2)
    windage_izz = d.windage_mass / 12.0 * (d.length**2 + d.breadth**2)

    _, cells_across = buoyancy_cells(d, wave)
    across = [(j - (cells_across - 1) / 2.0) for j in range(cells_across)]
    collisions = "".join(f"""
      <collision name="collision_hull_{i}_{j}">
        <pose>{_f(station.x)} {_f(dy * station.breadth / cells_across)} 0 0 0 0</pose>
        <geometry>
          <box>
            <size>{_f(station.length)} {_f(station.breadth / cells_across)} {_f(2.0 * station.depth)}</size>
          </box>
        </geometry>
      </collision>""" for i, station in enumerate(buoyancy_stations(d, wave)) for j, dy in enumerate(across))

    imu_sensor = (
        """
      <sensor name="imu_sensor" type="imu">
        <pose degrees="true">0 0 0 180 0 0</pose>
        <always_on>1</always_on>
        <update_rate>100.0</update_rate>
      </sensor>"""
        if ardupilot
        else ""
    )

    def thruster(name: str, y: float, parent: str = "base_link") -> str:
        return f"""
    <link name="motor_{name}_link">
      <pose>{_f(d.thruster_x)} {_f(y)} {_f(d.thruster_z)} 0 0 0</pose>
      <inertial>
        <mass>{_f(d.thruster_mass)}</mass>
        <inertia>{_inertia(thruster_ixx, thruster_iyy, thruster_iyy)}</inertia>
      </inertial>
    </link>
    <joint name="motor_{name}_joint" type="revolute">
      <parent>{parent}</parent>
      <child>motor_{name}_link</child>
      <axis>
        <xyz>1 0 0</xyz> <!-- thrust direction for the Thruster system -->
      </axis>
    </joint>
    <plugin filename="gz-sim-thruster-system" name="gz::sim::systems::Thruster">
      <joint_name>motor_{name}_joint</joint_name>
      <thrust_coefficient>{_f(d.thrust_coefficient)}</thrust_coefficient>
      <fluid_density>1025</fluid_density>
      <propeller_diameter>{_f(d.propeller_diameter)}</propeller_diameter>
      <!-- The propeller turns at the speed of the thrust (no propeller PID torque on the hull), and the
           system publishes that speed on .../ang_vel every iteration: the gz-transport actuator checks
           with it that a thrust command was in effect from the step's first iteration. -->
      <velocity_control>1</velocity_control>
      <use_angvel_cmd>0</use_angvel_cmd>
      <max_thrust_cmd>{_f(d.max_thrust)}</max_thrust_cmd>
      <min_thrust_cmd>{_f(-d.max_thrust)}</min_thrust_cmd>
    </plugin>"""

    # Far above any load on the helm: the steering gear holds its angle against the water.
    steering_effort = max(1.0e6, 10.0 * d.total_thrust * d.length)

    def steering_gear(geometry: str, ixx: float, iyy: float, izz: float, plugins: str = "") -> str:
        """The link that turns with the helm on steering_joint, and the controller that moves it at the helm's speed."""
        return f"""
    <link name="{STEERING_LINK}">
      <pose>{_f(d.steering_x)} 0 {_f(d.steering_z)} 0 0 0</pose>
      <inertial>
        <mass>{_f(d.steering_mass)}</mass>
        <inertia>{_inertia(ixx, iyy, izz)}</inertia>
      </inertial>
      <visual name="visual_steering">
        <geometry>
          {geometry}
        </geometry>
      </visual>
    </link>
    <!-- Helm angle, counterclockwise seen from above: positive turns the vessel to starboard. -->
    <joint name="{STEERING_JOINT}" type="revolute">
      <parent>base_link</parent>
      <child>{STEERING_LINK}</child>
      <axis>
        <xyz>0 0 1</xyz>
        <limit>
          <!-- Stops beyond hard over: a velocity commanded joint that reaches its stop stays on it (measured in
               gz-sim 8.15: the helm did not come back from hard over), so the commands end short of the stops. -->
          <lower>{_f(-d.steering_max_angle - STEERING_STOP_MARGIN)}</lower>
          <upper>{_f(d.steering_max_angle + STEERING_STOP_MARGIN)}</upper>
          <!-- A velocity commanded joint keeps its angle limits only with an effort limit (gz-physics JointFeatures). -->
          <effort>{_f(steering_effort)}</effort>
        </limit>
      </axis>
    </joint>
    <!-- Velocity commands: the joint moves toward the commanded angle at the helm's speed and stops on it. -->
    <plugin filename="gz-sim-joint-position-controller-system" name="gz::sim::systems::JointPositionController">
      <joint_name>{STEERING_JOINT}</joint_name>
      <topic>{steering_topic(agent_name)}</topic>
      <use_velocity_commands>true</use_velocity_commands>
      <cmd_max>{_f(d.steering_rate)}</cmd_max>
      <cmd_min>{_f(-d.steering_rate)}</cmd_min>
    </plugin>{plugins}"""

    steering = d.steering_type
    if steering == SteeringType.SKID.value:
        propulsion = thruster("port", d.thruster_y) + "\n" + thruster("stbd", -d.thruster_y)
    elif steering == SteeringType.RUDDER.value:
        thickness = RUDDER_THICKNESS_SHARE * d.rudder_chord
        blade = d.steering_mass / 12.0
        rudder_plugin = f"""
    <!-- The rudder's force: normal to the blade, the flow across it times the flow along it (yVabsU).
         A Hydrodynamics system of its own, so the blade's own frame turns with the helm. -->
    <plugin filename="gz-sim-hydrodynamics-system" name="gz::sim::systems::Hydrodynamics">
      <link_name>{STEERING_LINK}</link_name>
      <disable_coriolis>true</disable_coriolis>
      <disable_added_mass>true</disable_added_mass>
      <yVabsU>{_f(rudder_normal_force_coefficient(d.rudder_area, d.rudder_lift_slope))}</yVabsU>
    </plugin>"""
        propulsion = thruster("center", 0.0) + steering_gear(
            f"<box><size>{_f(d.rudder_chord)} {_f(thickness)} {_f(d.rudder_span)}</size></box>",
            blade * (thickness**2 + d.rudder_span**2),
            blade * (d.rudder_chord**2 + d.rudder_span**2),
            blade * (d.rudder_chord**2 + thickness**2),
            rudder_plugin,
        )
    else:
        mount_radius = d.propeller_diameter / 2.0
        mount_ixx = d.steering_mass / 12.0 * (3.0 * mount_radius**2 + d.motor_length**2)
        mount = steering_gear(f"<cylinder><radius>{_f(mount_radius)}</radius><length>{_f(d.motor_length)}</length></cylinder>", mount_ixx, mount_ixx, 0.5 * d.steering_mass * mount_radius**2)
        # The thruster hangs on the mount, so its thrust turns with the helm.
        propulsion = mount + thruster("center", 0.0, parent=STEERING_LINK)

    wave_buoyancy = (
        f"""

    <!-- Wave-aware buoyancy (asv_wave_sim, its system renamed WavesHydrodynamics in the Gazebo image so it
         loads next to the gz-sim Hydrodynamics system, which keeps the damping and added mass). -->
    <plugin filename="gz-waves1-hydrodynamics-system" name="gz::sim::systems::WavesHydrodynamics">
      <enable>{agent_name}::base_link</enable>
      <hydrodynamics>
        <damping_on>0</damping_on>
        <viscous_drag_on>0</viscous_drag_on>
        <pressure_drag_on>0</pressure_drag_on>
      </hydrodynamics>
    </plugin>"""
        if wave is not None
        else ""
    )

    def servo_channel(channel: int, joint: str, topic: str, multiplier: float, comment: str) -> str:
        return f"""
      <!-- {comment} -->
      <control channel="{channel}">
        <jointName>{joint}</jointName>
        <type>COMMAND</type>
        <cmd_topic>{topic}</cmd_topic>
        <multiplier>{_f(multiplier)}</multiplier>
        <offset>-0.5</offset>
        <servo_min>1000</servo_min>
        <servo_max>2000</servo_max>
      </control>"""

    ardupilot_plugin = ""
    if ardupilot:
        fdm_port_in = 9000 + vessel_id * 10 + 2
        thrust_multiplier = ardupilot_thrust_multiplier(d.max_thrust)
        if steering == SteeringType.SKID.value:
            channels = servo_channel(
                0, "motor_port_joint", thrust_topic(agent_name, "port"), thrust_multiplier, "Port motor, SERVO1_FUNCTION 73 (ThrottleLeft). PWM 1000 to 2000 is full astern to full ahead."
            )
            channels += servo_channel(2, "motor_stbd_joint", thrust_topic(agent_name, "stbd"), thrust_multiplier, "Starboard motor, SERVO3_FUNCTION 74 (ThrottleRight).")
        else:
            channels = servo_channel(
                0,
                STEERING_JOINT,
                steering_topic(agent_name),
                ardupilot_steering_multiplier(d.steering_max_angle),
                "Helm, SERVO1_FUNCTION 26 (GroundSteering). PWM 1000 to 2000 is hard over to port to hard over to starboard.",
            )
            channels += servo_channel(
                2, "motor_center_joint", thrust_topic(agent_name, "center"), thrust_multiplier, "Motor, SERVO3_FUNCTION 70 (Throttle). PWM 1000 to 2000 is full astern to full ahead."
            )
        ardupilot_plugin = f"""
    <plugin filename="ArduPilotPlugin" name="ArduPilotPlugin">
      <robotNamespace>{agent_name}</robotNamespace>
      <connectionTimeoutMaxCount>5</connectionTimeoutMaxCount>
      <lock_step>1</lock_step>
      <fdm_addr>0.0.0.0</fdm_addr>
      <fdm_port_in>{fdm_port_in}</fdm_port_in>
      <!-- Match ardupilot_gazebo iris: ENU world + FLU hull to NED / aircraft body. -->
      <modelXYZToAirplaneXForwardZDown>0 0 0 3.141592653589793 0 0</modelXYZToAirplaneXForwardZDown>
      <gazeboXYZToNED>0 0 0 3.141592653589793 0 1.5707963267948966</gazeboXYZToNED>
      <imuName>imu_sensor</imuName>{channels}
    </plugin>"""

    steering_summary = {
        SteeringType.SKID.value: f"skid steered by two thrusters of {_f(d.max_thrust)} N each: full differential thrust for {_f(d.design_yaw_rate)} rad/s",
        SteeringType.RUDDER.value: f"one thruster of {_f(d.max_thrust)} N and a rudder of {_f(d.rudder_area)} m2: hard over ({_f(math.degrees(d.steering_max_angle))} deg) for {_f(d.max_steady_yaw_rate)} rad/s at {_f(d.steering_speed)} m/s",
        SteeringType.VECTORED_THRUST.value: f"one thruster of {_f(d.max_thrust)} N turning with the helm: hard over ({_f(math.degrees(d.steering_max_angle))} deg) for {_f(d.max_steady_yaw_rate)} rad/s at {_f(d.steering_speed)} m/s",
    }[steering]
    commands = ", ".join(thrust_topic(agent_name, name) for name in thruster_names(steering))
    if steering != SteeringType.SKID.value:
        commands += f"; helm angle in rad on {steering_topic(agent_name)}"

    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <!-- Parametric vessel, control layer {control_layer.value}: L {_f(d.length)} m, B {_f(d.breadth)} m, draft {_f(d.draft)} m,
       block coefficient {_f(d.hull.block_coefficient)}, {_f(d.total_mass)} kg, full thrust for {_f(d.design_speed)} m/s;
       {steering_summary}.
       Commands: gz.msgs.Double thrust in N on {commands}. -->
  <model name="{agent_name}">
    <self_collide>false</self_collide>
    <!-- Avoid links auto-disabling mid-run (can destabilize coupled buoyancy/hydro). -->
    <allow_auto_disable>false</allow_auto_disable>
    <static>false</static>
    <!-- Pose is applied by the world via <include><pose> so this model stays reusable. Origin at the waterline. -->

    <link name="base_link">
      <inertial>
        <pose>0 0 {_f(d.com_z)} 0 0 0</pose>
        <mass>{_f(d.hull_mass)}</mass>
        <inertia>{_inertia(d.hull_ixx, d.hull_iyy, d.hull_izz)}</inertia>
      </inertial>
      <!-- Buoyant volume: boxes along the hull with its waterline breadth and mean depth, which displace the
           total mass at the draft (world Buoyancy system). Each is centered on the waterline and split into
           {BUOYANCY_GRID} or more cells across the hull so that roll is restored (see vessel_dynamics.BUOYANCY_GRID). -->{collisions}
      <!-- The hull surface, a mesh next to this file (hull_form.py). -->
      <visual name="visual_hull">
        <geometry>
          <mesh>
            <uri>{hull_mesh_filename(agent_name)}</uri>
          </mesh>
        </geometry>
        <material>
          <ambient>0.25 0.3 0.4 1</ambient>
          <diffuse>0.25 0.3 0.4 1</diffuse>
        </material>
      </visual>{imu_sensor}
    </link>

    <!-- Windage: the world WindEffects system pushes this link with mass * factor * relative wind,
         so its mass is the hull's air drag in N per m/s. Fixed to the hull at the center of the side area above water. -->
    <link name="windage_link">
      <pose>0 0 {_f(d.windage_z)} 0 0 0</pose>
      <enable_wind>true</enable_wind>
      <inertial>
        <mass>{_f(d.windage_mass)}</mass>
        <inertia>{_inertia(windage_ixx, windage_iyy, windage_izz)}</inertia>
      </inertial>
    </link>
    <joint name="windage_joint" type="fixed">
      <parent>base_link</parent>
      <child>windage_link</child>
    </joint>
{propulsion}

    <!-- Added-mass Coriolis terms off: their Munk moment makes a bare hull directionally unstable
         (measured: the 5 m hull spun under equal thrust above 2.5 m/s); real hulls are kept
         straight by skegs, which this model does not have. -->
    <plugin filename="gz-sim-hydrodynamics-system" name="gz::sim::systems::Hydrodynamics">
      <link_name>base_link</link_name>
      <disable_coriolis>true</disable_coriolis>
      <xDotU>{_f(d.xDotU)}</xDotU>
      <yDotV>{_f(d.yDotV)}</yDotV>
      <zDotW>{_f(d.zDotW)}</zDotW>
      <nDotR>{_f(d.nDotR)}</nDotR>
      <xU>{_f(d.xU)}</xU>
      <yV>{_f(d.yV)}</yV>
      <zW>{_f(d.zW)}</zW>
      <kP>{_f(d.kP)}</kP>
      <mQ>{_f(d.mQ)}</mQ>
      <nR>{_f(d.nR)}</nR>
      <xUabsU>{_f(d.xUabsU)}</xUabsU>
      <yVabsV>{_f(d.yVabsV)}</yVabsV>
      <nRabsR>{_f(d.nRabsR)}</nRabsR>
    </plugin>{wave_buoyancy}

    <plugin filename="gz-sim-joint-state-publisher-system" name="gz::sim::systems::JointStatePublisher">
    </plugin>

    <plugin filename="gz-sim-odometry-publisher-system" name="gz::sim::systems::OdometryPublisher">
      <odom_frame>odom</odom_frame>
      <robot_base_frame>base_link</robot_base_frame>
      <dimensions>3</dimensions>
      <odom_publish_frequency>{ODOMETRY_RATE_HZ}</odom_publish_frequency>
    </plugin>{ardupilot_plugin}
  </model>
</sdf>
"""
