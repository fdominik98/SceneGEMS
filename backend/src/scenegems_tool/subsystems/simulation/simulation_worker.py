import base64
import json
import logging
import math
import os
import queue
import threading
import time
from typing import List, Optional, Tuple

import numpy as np

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from scenegems_tool.gateway.protocol import SimulationStatus, simulation_config_from_body
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService, MqttStartSimulationTask
from scenegems_tool.subsystems.simulation.lockstep_simulation_driver import LockstepSimulationDriver, uses_lockstep_driver
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.simulation_parser import SimulationParser
from utils.global_constants import MAX_DISTANCE, ONE_SECOND
from utils.math_utils import rotate_heading as rotate_heading_util

_logger = logging.getLogger(__name__)


class SimulationWorker:
    """Runs simulation orchestration inside the simulation Docker container.

    An instance of simulated vessels runs through the registry's lockstep runners
    (lockstep_simulation_driver.py); one with real vessels through ArduAgent over WARA-PS MQTT
    (simulation_parser.py).
    """

    AGENTS_READY_POLL_INTERVAL_SEC = 1.0
    SIMULATOR_CLOCK_POLL_INTERVAL_SEC = 0.02
    SIMULATOR_CLOCK_STALL_WARNING_SEC = 10.0
    OBSTACLE_DISTANCES_UPDATE_INTERVAL_SEC = 0.1
    OBSTACLE_DISTANCES_RAY_INCREMENT = 5
    EVASIVE_FORWARD_PWM = 0.12
    EVASIVE_MIN_TURN_PWM = 0.15
    EVASIVE_MAX_TURN_PWM = 0.35
    EVASIVE_HEADING_DELTAS_DEG = (5, 10, 15, 20, 25)

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        simulation_config: SimulationInstanceConfig,
        trajectories: Trajectories,
        time_step: int,
    ):
        self.mqtt_service = MqttSimulationService(mqtt_connection, reference_geofence)
        self.simulation_config = simulation_config
        self.trajectories = trajectories
        self.time_step = time_step
        self._simulation_is_starting = False
        self._running_simulation_clock: Optional[float] = None
        self._stop_event = threading.Event()
        self._lockstep_stop = threading.Event()
        self._runtime_thread: Optional[threading.Thread] = None
        self._obstacle_distances_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self.publish_period = 1.0 / self.mqtt_service.info_update_rate
        self.lockstep_driver: Optional[LockstepSimulationDriver] = None
        self.simulation_parser: Optional[SimulationParser] = None
        if uses_lockstep_driver(simulation_config):
            self.lockstep_driver = LockstepSimulationDriver(simulation_config, trajectories, reference_geofence)
        else:
            self.simulation_parser = SimulationParser(
                simulation_config,
                trajectories,
                mqtt_connection,
                self.mqtt_service,
                spawn_docker_stack=False,
            )
        # self._start_obstacle_distances_loop()

    @classmethod
    def from_environment(cls, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence) -> "SimulationWorker":
        time_step = int(os.environ.get("TIME_STEP", ONE_SECOND))
        simulation_body = json.loads(base64.b64decode(os.environ["SIMULATION_CONFIG_JSON_B64"]).decode("utf-8"))
        trajectories_path = os.environ["TRAJECTORIES_PATH"]
        with open(trajectories_path, encoding="utf-8") as file:
            trajectories_data = json.load(file)
        simulation_config = simulation_config_from_body(simulation_body)
        trajectories = Trajectories.from_dict(trajectories_data)
        return cls(mqtt_connection, reference_geofence, simulation_config, trajectories, time_step)

    def run(self) -> None:
        self.mqtt_service.connect()
        self._publish_simulation_state()
        self._start_heartbeat_thread()
        next_state_publish_time = time.monotonic()
        try:
            while not self._stop_event.is_set():
                if not self.mqtt_service.is_connected:
                    self._stop_event.wait(0.1)
                    next_state_publish_time = time.monotonic()
                    continue
                now = time.monotonic()
                if now >= next_state_publish_time:
                    if self._running_simulation_clock is None:
                        self._publish_simulation_state()
                    next_state_publish_time = now + self.publish_period
                self._process_tasks()
                self._stop_event.wait(0.05)
        finally:
            self._stop_heartbeat_thread()
            self._stop_runtime()
            if self.simulation_parser is not None:
                self.simulation_parser.destroy()
            self.mqtt_service.disconnect()

    def stop(self) -> None:
        self._stop_event.set()

    def _start_heartbeat_thread(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="simulation_heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat_thread(self) -> None:
        if self._heartbeat_thread is None:
            return
        self._heartbeat_thread.join(timeout=self.publish_period + 1.0)
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        next_publish_time = time.monotonic()
        while not self._stop_event.is_set():
            if not self.mqtt_service.is_connected:
                self._stop_event.wait(0.1)
                next_publish_time = time.monotonic()
                continue

            now = time.monotonic()
            if now >= next_publish_time:
                self.mqtt_service.publish_heartbeat_and_sensor_info()
                next_publish_time = now + self.publish_period

            wait_period = max(0.0, min(next_publish_time - time.monotonic(), 0.1))
            self._stop_event.wait(wait_period)

    def _process_tasks(self) -> None:
        while True:
            try:
                task = self.mqtt_service.task_queue.get_nowait()
            except queue.Empty:
                return
            self.mqtt_service.track_task(task)
            try:
                self._handle_start_simulation(task)
            finally:
                self.mqtt_service.untrack_task(task)

    def _handle_start_simulation(self, task: MqttStartSimulationTask) -> None:
        del task
        self._stop_runtime()
        self._simulation_is_starting = True
        self._publish_simulation_state()
        self._runtime_thread = threading.Thread(target=self._run_simulation_runtime, name="simulation_runtime", daemon=True)
        self._runtime_thread.start()

    def _stop_runtime(self) -> None:
        self._simulation_is_starting = False
        self._running_simulation_clock = None
        if self._runtime_thread is not None and self._runtime_thread.is_alive():
            self._lockstep_stop.set()
            self._runtime_thread.join(timeout=5.0)
        self._runtime_thread = None
        self._lockstep_stop = threading.Event()

    def _start_obstacle_distances_loop(self) -> None:
        self._obstacle_distances_thread = threading.Thread(target=self._obstacle_distances_loop, name="obstacle_distances", daemon=True)
        self._obstacle_distances_thread.start()

    def _run_simulation_runtime(self) -> None:
        if self.lockstep_driver is not None:
            self._run_lockstep_runtime(self.lockstep_driver)
            return
        try:
            self.start_scenario()
            self._publish_simulation_state()
            if not self._wait_until_agents_running():
                self._simulation_is_starting = False
                self._publish_simulation_state()
                return
            self._simulation_is_starting = False
            self._stream_simulation_clock_ticks()
        except Exception:
            _logger.exception("Simulation runtime failed")
            self._simulation_is_starting = False
            self._publish_simulation_state()

    def _run_lockstep_runtime(self, driver: LockstepSimulationDriver) -> None:
        """Run the instance's lockstep runner; every step it records is published as the running clock and scene."""

        def on_scene(clock: float, scene) -> None:
            del scene  # the driver keeps it as the current scene
            self._simulation_is_starting = False
            self._running_simulation_clock = clock
            self._publish_simulation_state()

        try:
            driver.run(on_scene, self._lockstep_stop)
        except Exception:
            _logger.exception("Simulation lockstep run failed")
        finally:
            self._simulation_is_starting = False
            self._running_simulation_clock = None
            self._publish_simulation_state()

    def _wait_until_agents_running(self) -> bool:
        while not self.simulation_parser.are_agents_running:
            if self._stop_event.is_set():
                return False
            time.sleep(self.AGENTS_READY_POLL_INTERVAL_SEC)
        return True

    def _stream_simulation_clock_ticks(self) -> None:
        """Publish one state per time step of simulated time, read from the simulators.

        Every ArduAgent reports its SITL clock (SYSTEM_TIME). The scenario clock is the time
        that every vessel's simulator has advanced since the run started, so it slows down
        with the simulators instead of following the wall clock scaled by the speedup.
        Several steps that pass between two polls are published one by one, in order.
        """
        self._running_simulation_clock = 0.0
        self._publish_simulation_state()
        origins = self._wait_for_simulator_clocks()
        if origins is None:
            self._running_simulation_clock = None
            return
        step = float(self.time_step)
        last_advance_at = time.monotonic()
        while not self._stop_event.is_set():
            if not self.simulation_parser.are_agents_running:
                self._running_simulation_clock = None
                return
            elapsed = [clock - origin for clock, origin in zip(self.simulation_parser.simulator_clocks, origins)]
            while self._running_simulation_clock is not None and self._running_simulation_clock + step <= min(elapsed):
                self._running_simulation_clock += step
                # Publishing resets the clock to None when the agents stopped running.
                self._publish_simulation_state()
                last_advance_at = time.monotonic()
            if self._running_simulation_clock is None:
                return
            if time.monotonic() - last_advance_at > self.SIMULATOR_CLOCK_STALL_WARNING_SEC:
                _logger.warning("Simulator clocks have not advanced a time step for %.0f s (elapsed per vessel: %s)", self.SIMULATOR_CLOCK_STALL_WARNING_SEC, elapsed)
                last_advance_at = time.monotonic()
            self._stop_event.wait(self.SIMULATOR_CLOCK_POLL_INTERVAL_SEC)

    def _wait_for_simulator_clocks(self) -> Optional[List[float]]:
        """Simulator clock of every vessel at the start of the run, once each has reported one."""
        while not self._stop_event.is_set():
            if not self.simulation_parser.are_agents_running:
                return None
            clocks = self.simulation_parser.simulator_clocks
            if all(clock > 0 for clock in clocks):
                return clocks
            self._stop_event.wait(self.SIMULATOR_CLOCK_POLL_INTERVAL_SEC)
        return None

    def _compute_status(self) -> SimulationStatus:
        if self.lockstep_driver is not None:
            # The runner connects to the simulators when the run starts, so the instance is ready right away.
            if self.lockstep_driver.is_running:
                return SimulationStatus.RUNNING
            return SimulationStatus.STARTING if self._simulation_is_starting else SimulationStatus.READY_TO_START
        if self.simulation_parser.are_agents_running:
            return SimulationStatus.RUNNING
        if self._simulation_is_starting:
            return SimulationStatus.STARTING
        if self.simulation_parser.are_agents_ready:
            return SimulationStatus.READY_TO_START
        if self.simulation_parser.are_agents_initialized:
            return SimulationStatus.AGENTS_ARE_PREPARING
        return SimulationStatus.INITIALIZING

    def get_current_scene(self) -> Optional[ConcreteScene]:
        if self.lockstep_driver is not None:
            return self.lockstep_driver.current_scene
        return self.simulation_parser.get_current_scene

    @property
    def _agents_initialized(self) -> bool:
        return self.lockstep_driver is not None or self.simulation_parser.are_agents_initialized

    def _publish_simulation_state(self) -> None:
        status = self._compute_status()
        if status == SimulationStatus.RUNNING:
            clock = self._running_simulation_clock if self._running_simulation_clock is not None else 0.0
        else:
            self._running_simulation_clock = None
            clock = 0.0
        scene = self.get_current_scene()
        scene_dict = scene.to_dict() if scene is not None and self._agents_initialized else None
        self.mqtt_service.publish_simulation_state(status=status, clock=clock, scene=scene_dict)

    def start_scenario(self) -> None:
        if not self.simulation_parser.are_agents_ready:
            raise RuntimeError("Cannot start scenario: agents are not ready to start")
        for client in self.simulation_parser.clients:
            if client.on_board_control_mode:
                continue
            max_speed = self.trajectories.get_max_speed(client.actor)
            if client.external_control_mode:
                client.publish_go_to(
                    np.array([client.mission_waypoints[-1]["latitude"], client.mission_waypoints[-1]["longitude"]]),
                    max_speed,
                )
            else:
                client.publish_follow_path(client.mission_waypoints, max_speed)

    def _obstacle_distances_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.OBSTACLE_DISTANCES_UPDATE_INTERVAL_SEC)
            try:
                self._publish_obstacle_distances()
            except Exception:
                _logger.exception("Error publishing obstacle avoidance")

    def _publish_obstacle_distances(self) -> None:
        if not self.simulation_parser.are_agents_initialized:
            return
        scene = self.get_current_scene()
        if scene is None:
            return
        os_client = self.simulation_parser.os_client
        os_actor = os_client.actor
        os_circular_safety_domain = os_client.actor.get_default_safety_domain(os_client.current_agent_state)
        increment = self.OBSTACLE_DISTANCES_RAY_INCREMENT
        min_distance = os_circular_safety_domain.radius
        obstacle_distances = os_circular_safety_domain.get_ray_distances(
            [actor.get_default_safety_domain(scene[actor]) for actor in scene.actors if actor != os_client.actor],
            increment,
            min_distance,
            MAX_DISTANCE,
        )
        os_client.publish_obstacle_distances(obstacle_distances, increment, min_distance, MAX_DISTANCE)
        evasive_pwm = self._compute_evasive_pwm(scene, os_actor, obstacle_distances, increment)
        os_client.publish_rc_override(evasive_pwm)

    def _preferred_turn_sign_from_rays(
        self,
        obstacle_distances: List[float],
        increment: int,
        heading_rad: float,
    ) -> Optional[float]:
        heading_deg = math.degrees(heading_rad) % 360
        port_clearance = 0.0
        starboard_clearance = 0.0
        for idx, dist in enumerate(obstacle_distances):
            angle_deg = (idx * increment) % 360
            rel_deg = (angle_deg - heading_deg + 180) % 360 - 180
            if -90 <= rel_deg < -10:
                port_clearance += dist
            elif 10 < rel_deg <= 90:
                starboard_clearance += dist
        if abs(port_clearance - starboard_clearance) < 1e-6:
            return None
        return 1.0 if port_clearance > starboard_clearance else -1.0

    def _find_evasive_pwm_for_turn_sign(self, scene: ConcreteScene, os_actor, turn_sign: float) -> Optional[Tuple[float, float]]:
        os_state = scene[os_actor]
        for delta_deg in self.EVASIVE_HEADING_DELTAS_DEG:
            trial_heading = rotate_heading_util(os_state.heading, turn_sign * math.radians(delta_deg))
            trial_scene = SceneBuilder(scene).set_state(os_actor, os_state.modify_copy(heading=trial_heading)).build()
            if not trial_scene.may_collide_anyone(os_actor):
                turn_strength = min(
                    self.EVASIVE_MAX_TURN_PWM,
                    self.EVASIVE_MIN_TURN_PWM + delta_deg / 100.0,
                )
                forward = self.EVASIVE_FORWARD_PWM
                return (
                    max(-1.0, min(1.0, forward + turn_strength * turn_sign)),
                    max(-1.0, min(1.0, forward - turn_strength * turn_sign)),
                )
        return None

    def _compute_evasive_pwm(
        self,
        scene: ConcreteScene,
        os_actor,
        obstacle_distances: List[float],
        increment: int,
    ) -> Optional[Tuple[float, float]]:
        if not scene.may_collide_anyone(os_actor):
            return None
        os_state = scene[os_actor]
        preferred_turn = self._preferred_turn_sign_from_rays(obstacle_distances, increment, os_state.heading)
        turn_order = [preferred_turn, -preferred_turn] if preferred_turn is not None else [1.0, -1.0]
        for turn_sign in turn_order:
            if turn_sign is None:
                continue
            pwm = self._find_evasive_pwm_for_turn_sign(scene, os_actor, turn_sign)
            if pwm is not None:
                return pwm
        if preferred_turn is not None:
            forward = self.EVASIVE_FORWARD_PWM
            turn = self.EVASIVE_MIN_TURN_PWM
            return (
                max(-1.0, min(1.0, forward + turn * preferred_turn)),
                max(-1.0, min(1.0, forward - turn * preferred_turn)),
            )
        return None
