import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.simulators.gazeboo.hydrodynamics import calculate_hydrodynamics
from scenegems_tool.simulators.gazeboo.thrust_calculation import calculate_thrust_coefficient, calculate_thrust_multiplier


def generate_vessel_model(vessel: ConcreteVessel, agent_name: str) -> str:
    fdm_port_in = 9000 + int(vessel.id) * 10 + 2

    # Fixing variables for stability
    length = 5.0
    breadth = length * 0.5
    height = length * 0.15
    draft = height * 0.4
    block_coefficient = 0.6
    total_mass = 1025 * block_coefficient * length * breadth * draft
    # rudder_mass = mass * 0.01
    rudder_mass = 0.0
    r_l, r_b, r_h = length * 0.02, 0.1, height * 0.8
    thruster_mass = total_mass * 0.001
    mass = total_mass - 2 * thruster_mass
    prop_diameter = draft * 0.6
    motor_length = prop_diameter * 1.5

    vessel = ConcreteVessel(
        id=vessel.id,
        type=vessel.name,
        length=length,
        breadth=breadth,
        height=height,
        draft=draft,
        safety_radius=vessel.safety_radius,
        _is_os=vessel.is_os,
        _rudder_mass=rudder_mass,
        _rudder_length=r_l,
        _rudder_width=r_b,
        _rudder_height=r_h,
        _propeller_diameter=prop_diameter,
        _thruster_mass=thruster_mass,
        _motor_length=motor_length,
        _max_speed=vessel.max_speed,
        _max_angular_speed=vessel.max_angular_speed,
        _max_acceleration=vessel.max_acceleration,
        mass=mass,
    )

    # ============================================================
    # GEOMETRY DEFINITIONS
    # ============================================================
    # Coordinate convention:
    # z = 0  -> waterline
    # +z     -> above water
    # -z     -> below water
    draft = vessel.draft
    freeboard = vessel.visible_height
    total_height = draft + freeboard
    # ============================================================
    # CENTER OF MASS
    # ============================================================
    # Slightly below waterline for roll stability
    # ~10-20% of draft is usually sufficient.
    # Move CoM up closer to the actual submerged volume center
    com_z = -draft * 1.5
    com_x = vessel.length / 2 * 0.1  # Keep slight rearward weight bias
    # ============================================================
    # COLLISION HULL (SUBMERGED VOLUME)
    # ============================================================
    collision_hull_size = np.array([vessel.length, vessel.breadth, draft])
    # Box centered halfway below waterline
    collision_hull_pose_z = -draft * 0.5
    # ============================================================
    # VISUAL HULL (FULL SHIP BODY)
    # ============================================================
    visual_hull_size = np.array([vessel.length, vessel.breadth, total_height])
    # Center full hull around waterline
    #
    # Example:
    # draft = 1.2
    # freeboard = 1.8
    #
    # hull extends:
    #   +1.8 above water
    #   -1.2 below water
    #
    visual_hull_pose_z = (freeboard - draft) * 0.5

    # Place thrusters at the stern (95% back) and inset from the sides (80% of width)
    thruster_x = -(vessel.length / 2) * 0.9
    thruster_y = (vessel.breadth / 2) * 0.8
    thruster_z = com_z

    # Hull Inertia
    # Roll : set it moderate
    hull_ixx = 1 / 12 * vessel.mass * (vessel.breadth**2 + vessel.height**2)
    # Pitch: set it large
    hull_iyy = 1 / 12 * vessel.mass * (vessel.height**2 + vessel.length**2)
    # Yaw : set it huge
    hull_izz = 1 / 12 * vessel.mass * (vessel.length**2 + vessel.breadth**2)

    # Thrusters Inertia
    thruster_radius = vessel.propeller_diameter / 2
    thruster_ixx = 0.5 * vessel.thruster_mass * (thruster_radius**2)
    thruster_iyy = (vessel.thruster_mass / 12.0) * (3 * thruster_radius**2 + vessel.motor_length**2)
    thruster_izz = thruster_iyy

    hydro = calculate_hydrodynamics(vessel, hull_izz)
    # added mass
    xDotU = hydro["xDotU"]
    yDotV = hydro["yDotV"]
    zDotW = hydro["zDotW"]
    nDotR = hydro["nDotR"]

    # linear damping
    xU = hydro["xU"]
    yV = hydro["yV"]
    zW = hydro["zW"]
    nR = hydro["nR"]

    # quadratic damping
    xUU = hydro["xUU"]
    yVV = hydro["yVV"]
    zWW = hydro["zWW"]
    nRR = hydro["nRR"]

    hydro1 = f""" 
<!-- use only if we want gazebo to automatically calculate Fossen matrix -->
<hydrodynamics>
      <damping_on>1</damping_on>
      <viscous_drag_on>1</viscous_drag_on>
      <pressure_drag_on>1</pressure_drag_on>
</hydrodynamics>  

<nR>{nR}</nR>
<nDotR>{nDotR}</nDotR>
<nRabsR>{nRR}</nRabsR>
<yVabsV>{yVV}</yVabsV>
<yDotV>{yDotV}</yDotV>
<yV>{yV}</yV>
"""

    hydro2 = f"""
<!-- Added mass -->
<xDotU>{xDotU}</xDotU>
<yDotV>{yDotV}</yDotV>
<zDotW>{zDotW}</zDotW>
<nDotR>{nDotR}</nDotR>

<!-- Linear damping -->
<xU>{xU}</xU>
<yV>{yV}</yV>
<zW>{zW}</zW>
<nR>{nR}</nR>

<!-- Quadratic damping -->
<xUabsU>{xUU}</xUabsU>
<yVabsV>{yVV}</yVabsV>
<zWabsW>{zWW}</zWabsW>
<nRabsR>{nRR}</nRabsR>
"""

    hydro3 = f"""
<xDotU>-115.0</xDotU>
<yDotV>-1500.5</yDotV>
<zDotW>-1150.8</zDotW>
<nDotR>-5000.0</nDotR> 

<xU>-25.0</xU>
<yV>-1000.0</yV>
<zW>-230.0</zW>
<nR>-2000.0</nR> 

<xUabsU>-50.0</xUabsU>
<yVabsV>-5000.0</yVabsV>
<zWabsW>-7687.5</zWabsW>
<nRabsR>-7000.0</nRabsR>
"""

    hydro_plugin_fragment = f"""
   <plugin filename="gz-sim-hydrodynamics-system" name="gz::sim::systems::Hydrodynamics">
    <link_name>base_link</link_name>
    <enable>base_link</enable>
    {hydro3}
   </plugin>
   """

    thrust_coefficient = calculate_thrust_coefficient(vessel, xU, xUU, xDotU)
    thrust_multiplier = calculate_thrust_multiplier(vessel, xU, xUU, 2) * 0.01
    thrust_multiplier = 500
    model_template = f"""
<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{agent_name}">
    <self_collide>false</self_collide>
    <!-- Avoid links auto-disabling mid-run (can destabilize coupled buoyancy/hydro). -->
    <allow_auto_disable>false</allow_auto_disable>
    <static>false</static>
    <!-- Pose is applied by the world via <include><pose> so this model stays reusable. -->

    <link name="base_link">
      <inertial>
        <!-- CoM slightly below geometric center for roll stability (scaled from large vessel). -->
        <pose>0 0 {com_z}  0 0 0</pose>
        <mass>{vessel.mass}</mass>
        <inertia>
          <!-- kg*m^2; izz lowered for snappier yaw; iyy chosen so ixx+izz >= iyy (valid rigid body). -->
          <ixx>{hull_ixx}</ixx>
          <iyy>{hull_iyy}</iyy>
          <izz>{hull_izz}</izz>
          <ixy>0</ixy>
          <ixz>0</ixz>
          <iyz>0</iyz>
        </inertia>
      </inertial>

      <collision name="collision_hull">
        <pose>0 0 {collision_hull_pose_z} 0 0 0</pose>
        <geometry>
          <box>
            <size>{collision_hull_size[0]} {collision_hull_size[1]} {collision_hull_size[2]}</size>
          </box>
        </geometry>
      </collision>

      <visual name="visual_hull">
        <pose>0 0 {visual_hull_pose_z} 0 0 0</pose>
        <geometry>
          <box>
            <size>{visual_hull_size[0]} {visual_hull_size[1]} {visual_hull_size[2]}</size>
          </box>
        </geometry>
      </visual>
      
      <sensor name="imu_sensor" type="imu">
        <pose degrees="true">0 0 0 180 0 0</pose>
        <always_on>1</always_on>
        <update_rate>100.0</update_rate>
      </sensor>
      <!--<sensor name="navsat_sensor" type="navsat">
        <pose>0 0 0 0 0 0</pose>
        <always_on>1</always_on>
        <update_rate>10.0</update_rate>
      </sensor>-->
  </link>
  
  <!-- MATHEMATICAL THRUST ANCHORS (Invisible, no collision, locked to hull) -->
    <link name="motor_stbd_link">
      <pose degrees="true">{thruster_x} {-thruster_y} {thruster_z} 0 0 0</pose>
      <inertial>
        <mass>{vessel.thruster_mass}</mass>
        <inertia>
          <ixx>{thruster_ixx}</ixx><iyy>{thruster_iyy}</iyy><izz>{thruster_izz}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>
        </inertia>
      </inertial>
    </link>

    <joint name="motor_stbd_joint" type="revolute">
      <parent>base_link</parent>
      <child>motor_stbd_link</child>
      <axis>
        <xyz> 1 0 0</xyz> <!-- The Thruster plugin reads this to know the thrust direction -->
      </axis>
    </joint>

    <link name="motor_port_link">
      <pose degrees="true">{thruster_x} {thruster_y} {thruster_z} 0 0 0</pose>
      <inertial>
        <mass>{vessel.thruster_mass}</mass>
        <inertia>
          <ixx>{thruster_ixx}</ixx><iyy>{thruster_iyy}</iyy><izz>{thruster_izz}</izz>
          <ixy>0</ixy><ixz>0</ixz><iyz>0</iyz>
        </inertia>
      </inertial>
    </link>

    <joint name="motor_port_joint" type="revolute">
      <parent>base_link</parent>
      <child>motor_port_link</child>
      <axis>
        <xyz> 1 0 0 </xyz> <!-- The Thruster plugin reads this to know the thrust direction -->
      </axis>
    </joint>

  {hydro_plugin_fragment}


  <plugin name="gz::sim::systems::JointStatePublisher"
      filename="gz-sim-joint-state-publisher-system">
  </plugin>

  <plugin name="gz::sim::systems::OdometryPublisher"
      filename="gz-sim-odometry-publisher-system">
      <odom_frame>odom</odom_frame>
      <robot_base_frame>base_link</robot_base_frame>
      <dimensions>3</dimensions>
  </plugin>

    <plugin filename="gz-sim-thruster-system" name="gz::sim::systems::Thruster">
      <joint_name>motor_port_joint</joint_name>
      <thrust_coefficient>{thrust_coefficient}</thrust_coefficient>
      <fluid_density>1025</fluid_density>
      <propeller_diameter>{vessel.propeller_diameter}</propeller_diameter>
      <velocity_control>0</velocity_control>
      <use_angvel_cmd>0</use_angvel_cmd>
    </plugin>

  <plugin filename="gz-sim-thruster-system" name="gz::sim::systems::Thruster">
    <joint_name>motor_stbd_joint</joint_name>
    <thrust_coefficient>{thrust_coefficient}</thrust_coefficient>
    <fluid_density>1025</fluid_density>
    <propeller_diameter>{vessel.propeller_diameter}</propeller_diameter>
    <velocity_control>0</velocity_control>
    <use_angvel_cmd>0</use_angvel_cmd>
  </plugin>

  <plugin filename="ArduPilotPlugin" name="ArduPilotPlugin">
    <robotNamespace>{agent_name}</robotNamespace>
    <connectionTimeoutMaxCount>5</connectionTimeoutMaxCount>
    <lock_step>1</lock_step>
    <fdm_addr>0.0.0.0</fdm_addr>
    <fdm_port_in>{fdm_port_in}</fdm_port_in>
    <!-- Match ardupilot_gazebo iris: ENU world + FLU hull -> NED / aircraft body. -->
    <modelXYZToAirplaneXForwardZDown>0 0 0 3.141592653589793 0 0</modelXYZToAirplaneXForwardZDown>
    <gazeboXYZToNED>0 0 0 3.141592653589793 0 1.5707963267948966</gazeboXYZToNED>
    <imuName>imu_sensor</imuName>

    <!--
      port motor cw

      SERVO1_FUNCTION 73 (ThrottleLeft)
      SERVO1_MAX 2000
      SERVO1_MIN 1000
    -->
    <control channel="0">
      <jointName>motor_port_joint</jointName>
      <type>COMMAND</type>
      <cmd_topic>/model/{agent_name}/joint/motor_port_joint/cmd_thrust</cmd_topic>
      <multiplier>{thrust_multiplier}</multiplier>
      <offset>-0.5</offset>
      <servo_min>1000</servo_min>
      <servo_max>2000</servo_max>
    </control>

    <!--
      stbd motor ccw

      SERVO3_FUNCTION 74 (ThrottleRight)
      SERVO3_MAX 2000
      SERVO3_MIN 1000
    -->
    <control channel="2">
      <jointName>motor_stbd_joint</jointName>
      <type>COMMAND</type>
      <cmd_topic>/model/{agent_name}/joint/motor_stbd_joint/cmd_thrust</cmd_topic>
      <multiplier>{thrust_multiplier}</multiplier>
      <offset>-0.5</offset>
      <servo_min>1000</servo_min>
      <servo_max>2000</servo_max>
    </control>
  </plugin>

  </model>
</sdf>

    """
    return model_template
