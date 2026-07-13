# flake8: noqa: W293
from typing import List, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from scenegems_tool.simulators.simulation_config import WaveConfig
from utils.global_constants import MAX_COORD


def _vessel_include(uri: str, state: ActorState) -> str:
    """Include a generated vessel model by URI and place it via the world (model stays pose-free)."""
    return f"""    <include>
      <uri>{uri}</uri>
      <pose>{state.x} {state.y} 0 0 0 {state.heading}</pose>
    </include>"""


def generate_world(center: np.ndarray, vessel_includes: List[Tuple[str, ActorState]], wind_vector: np.ndarray, wave: WaveConfig, speed_factor: int, headless: bool) -> str:
    vessel_block = "\n".join(_vessel_include(uri, state) for uri, state in vessel_includes)

    scene_broadcaster_block = (
        """
    <plugin filename="gz-sim-scene-broadcaster-system"
      name="gz::sim::systems::SceneBroadcaster">
    </plugin>
    """
        if not headless
        else ""
    )

    buoyancy_block = """
    <!-- Buoyancy at flat sea level (z=0); visual water is static mesh below (no Waves system). -->
    <plugin filename="gz-sim-buoyancy-system" name="gz::sim::systems::Buoyancy">
      <graded_buoyancy>
        <default_density>1025</default_density>
        <density_change>
          <above_depth>0</above_depth>
          <density>1.225</density>
          <!-- Air density -->
        </density_change>
      </graded_buoyancy>
      <enable_water_velocity>true</enable_water_velocity>
    </plugin>
    """

    world_template = f"""
    

<?xml version="1.0" ?>
<sdf version="1.9">
<world name="ocean_world">
    <!-- DART defaults to ODE collision; ODE can abort with aabbBound asserts on some
         multi-link / buoyancy-heavy setups. Use Bullet broadphase for collision detection. -->
    <physics name="1ms" type="ignored">
    <!-- Slightly smaller step helps constraint-heavy marine models (thrusters + buoyancy + hydro). -->
    <max_step_size>0.005</max_step_size>
    <real_time_factor>{speed_factor}</real_time_factor>
    <!-- <dart> 
      <collision_detector>bullet</collision_detector>
      <solver>
        <solver_type>pgs</solver_type>
      </solver>
    </dart>-->
    </physics>
    
    <plugin filename="gz-sim-physics-system"
      name="gz::sim::systems::Physics">
    </plugin>
    <plugin
      filename="gz-sim-sensors-system"
      name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
      <background_color>0.8 0.8 0.8</background_color>
    </plugin>
    <plugin filename="gz-sim-user-commands-system"
      name="gz::sim::systems::UserCommands">
    </plugin>
    {scene_broadcaster_block}
    <plugin filename="gz-sim-imu-system"
      name="gz::sim::systems::Imu">
    </plugin>
    <plugin filename="gz-sim-navsat-system"
      name="gz::sim::systems::NavSat">
    </plugin>
    <plugin name="gz::sim::systems::Anemometer"
      filename="asv_sim2-anemometer-system">
    </plugin>
    <gravity>0 0 -9.81</gravity>
    
    <spherical_coordinates>
        <surface_model>EARTH_WGS84</surface_model>

        <latitude_deg>{center[0]}</latitude_deg>
        <longitude_deg>{center[1]}</longitude_deg>

        <elevation>0</elevation>
        <heading_deg>0</heading_deg>
    </spherical_coordinates>
    

    <!-- Ocean Waves System (Visual & Physics) -->
    <!-- <plugin filename="gz-sim-waves-system" name="gz::sim::systems::Waves">
    <ocean_shape>
        <mesh_size>{MAX_COORD} {MAX_COORD}</mesh_size>
        <cell_count>0 0</cell_count>
        <wave_amplitude>{wave.amplitude}</wave_amplitude>
        <wave_period>{wave.period}</wave_period>
        <direction>{wave.direction[0]} {wave.direction[1]}</direction>
    </ocean_shape>
    </plugin> -->

    <plugin filename="asv_sim2-wind-system"
      name="gz::sim::systems::Wind">
      <topic>/wind</topic>
    </plugin>


    {buoyancy_block}


    <scene>
        <ambient>0.8 0.8 0.8 1</ambient>
        <background>0.5 0.7 0.9 1</background>
        <grid>false</grid>
        <sky></sky>
    </scene>


    <light type="directional" name="sun">
        <cast_shadows>true</cast_shadows>
        <pose>0 0 100 0 0 0</pose>
        <diffuse>1 1 1 1</diffuse>
        <specular>0.5 0.5 0.5 1</specular>
        <direction>-0.5 0.1 -0.9</direction>
    </light>


    <!-- Static sea surface: large plane mesh, visual only (no collision). -->
    <model name="water_surface">
    <static>true</static>
    <pose>0 0 0 0 0 0</pose>
    <link name="water_link">
        <visual name="water_visual">
        <pose>0 0 0 0 0 0</pose>
        <transparency>0.25</transparency>
        <geometry>
            <plane>
            <normal>0 0 1</normal>
            <!-- size: meters (full width and height of the plane) -->
            <size>{MAX_COORD} {MAX_COORD}</size>
            </plane>
        </geometry>
        <material>
            <ambient>0.05 0.28 0.42 0.85</ambient>
            <diffuse>0.08 0.38 0.58 0.8</diffuse>
            <specular>0.6 0.65 0.7 1</specular>
            <emissive>0 0 0 1</emissive>
        </material>
        </visual>
    </link>
    </model>
    <!-- Global Wind -->
    <wind>
    <linear_velocity>{wind_vector[0]} {wind_vector[1]} {wind_vector[2]}</linear_velocity>
    </wind>
    
    <!-- Vessel Models -->
    {vessel_block}
</world>
</sdf>
    """
    return world_template
