"""Drives an attended run with a real vessel: every vessel through its ArduAgent, over MQTT.

A real vessel is reached only through the ArduAgent on board, so an instance with one runs every
vessel that way: a simulated vessel gets SITL, MAVProxy and an ArduAgent of its own in the job's
stack, and the driver talks to all of them on one broker (the cluster's, or an external one such
as WARA-PS's). An instance of simulated vessels only runs in lockstep instead
(lockstep_simulation_driver.py).

Before the run the driver tells where each vessel is (vessel_states): connected, reporting its
position, armable and at the point the scenario starts it from. The run sends every vessel its
task once (replay follows the trajectory as a mission, Mission Planner is sent toward its last
waypoint and left to its operator, an on_board vessel is sent nothing) and then follows the
scenario clock: the time every vessel has advanced since the start, read from the clock its
ArduAgent reports (its autopilot's SYSTEM_TIME), so the clock slows down with the simulators. A
vessel that reports no clock is taken on the wall clock, which is the clock of a real vessel.
Every time step that has passed is one scene of where the vessels are, in order.

The run ends at the trajectories' time span, or earlier when the commanded vessels stop (a task
that finished, failed or was aborted). Nothing is sent to a vessel when a run ends or is stopped:
it finishes its task on its own.
"""

import hashlib
import json
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import paho.mqtt.client as mqtt

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_agent_client import ExecutionState, MqttAgentClient
from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.messaging.topic_layout import parse_unit_topic, service_topic
from scenegems_tool.vessel_stack.asv_system.replay.replay_mission import cap_mission_trajectories, replay_mission_waypoints
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.arduagent_control_mode import ARDUAGENT_ADAPTER_IDS, arduagent_control_mode
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver, StackUnavailableError

SceneObserver = Callable[[float, ConcreteScene], None]  # (scenario time in s, the scene at that time)

CONNECTED = "connected"
POSITION = "position"
ARMABLE = "armable"
AT_START = "at_start"


class VesselsNotReady(RuntimeError):
    """A run was started while a vessel was not connected, not at its start point or not armable."""


def agent_unit_name(topic: str, fallback: str) -> str:
    """The name an ArduAgent has on the broker: the last level of its topic in the unit layout, else the fallback."""
    unit = parse_unit_topic(topic)
    return unit.name if unit is not None else fallback


class SimulationSubsystemPresence(MqttClient):
    """The simulation subsystem of one job on the broker: its heartbeat, under the name the vessels' commands carry as their sender."""

    def __init__(self, name: str, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.info_update_rate = 1.0
        super().__init__(name, service_topic(mqtt_connection.topic_root, name), mqtt_connection, reference_geofence)

    @property
    def listen_topics(self) -> List[str]:
        return []

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any) -> None:
        del msg, payload

    def publish_heartbeat(self, stamp: float) -> None:
        heartbeat = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Simulation Subsystem",
            "agent-uuid": self.uuid,
            "levels": [],
            "rate": self.info_update_rate,
            "stamp": stamp,
            "type": "HeartBeat",
        }
        self.client.publish(self.heartbeat_topic, json.dumps(heartbeat), qos=1)


@dataclass
class ArduAgentRun:
    """What an ArduAgent run observed: every vessel's state at every time step, and how the run was made."""

    vessel_ids: List[int]
    states: List[List[ActorState]] = field(default_factory=list)  # per recorded scene (the start included), per vessel
    run_record: Dict[str, Any] = field(default_factory=dict)

    @property
    def steps(self) -> int:
        return max(len(self.states) - 1, 0)

    def state_digest(self) -> str:
        """SHA-256 over the exact float64 bits of every recorded state, as the lockstep runners digest theirs."""
        digest = hashlib.sha256()
        for step_states in self.states:
            for state in step_states:
                digest.update(struct.pack("<4d", float(state.x), float(state.y), float(state.speed), float(state.heading)))
        return digest.hexdigest()


class ArduAgentSimulationDriver:
    kind = "arduagent"
    POLL_INTERVAL_S = 0.02
    HEARTBEAT_INTERVAL_S = 1.0

    def __init__(
        self,
        simulation: SimulationInstanceConfig,
        trajectories: Trajectories,
        reference_geofence: Geofence,
        mqtt_connection: MQttConnectionInfo,
        service_name: str,
        *,
        resolver: Optional[StackResolver] = None,
        client_factory: Callable[..., Any] = MqttAgentClient,
        presence_factory: Callable[..., Any] = SimulationSubsystemPresence,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
    ):
        self.simulation = simulation
        self.trajectories = trajectories
        self.reference_geofence = reference_geofence
        self.mqtt_connection = mqtt_connection
        self.service_name = service_name
        self.resolution = (resolver or default_resolver()).require_instance(simulation)
        not_arduagent = [
            f"vessel {agent_id} uses {chain.asv_adapter.id if chain.asv_adapter else 'no adapter'}"
            for agent_id, chain in self.resolution.chains.items()
            if chain.asv_adapter is None or chain.asv_adapter.id not in ARDUAGENT_ADAPTER_IDS
        ]
        if not_arduagent:
            raise StackUnavailableError([f"the ArduAgent driver runs vessels only through ArduAgent: {', '.join(not_arduagent)}"])
        self._client_factory = client_factory
        self._presence_factory = presence_factory
        self._sleep = sleep
        self._clock = clock
        self._wall_time = wall_time
        self.clients: Dict[str, Any] = {}  # by agent id, in the instance's order
        self.presence: Optional[Any] = None
        self._last_heartbeat: Optional[float] = None

    def connect(self) -> None:
        """Connects the subsystem's presence and one client per vessel; RuntimeError when the broker cannot be reached."""
        self.presence = self._presence_factory(self.service_name, self.mqtt_connection, self.reference_geofence)
        self.presence.connect()
        mission_trajectories = cap_mission_trajectories(self.trajectories)
        for agent_id, vessel_config in self.simulation.vessels.items():
            vessel = self.trajectories.initial_scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
            connection = vessel_config.require_connection()
            waypoints = replay_mission_waypoints(mission_trajectories, vessel, self.trajectories.get_max_speed(vessel), self.reference_geofence)
            client = self._client_factory(
                vessel=vessel,
                mqtt_connection=self.mqtt_connection,
                topic=connection.topic,
                control_mode=arduagent_control_mode(vessel_config.stack.asv_system),
                agent_name=agent_unit_name(connection.topic, connection.agent_name),
                reference_geofence=self.reference_geofence,
                initial_state=self.trajectories.initial_scene[vessel],
                parent_service_name=self.service_name,
                mission_waypoints=waypoints,
            )
            client.connect()
            self.clients[agent_id] = client
            client.publish_trajectory([[point["latitude"], point["longitude"]] for point in waypoints])

    def close(self) -> None:
        for client in self.clients.values():
            client.disconnect()
        if self.presence is not None:
            self.presence.disconnect()

    def heartbeat(self) -> None:
        """The subsystem's heartbeat, once per HEARTBEAT_INTERVAL_S however often it is asked for."""
        now = self._clock()
        if self.presence is None or (self._last_heartbeat is not None and now - self._last_heartbeat < self.HEARTBEAT_INTERVAL_S):
            return
        self._last_heartbeat = now
        self.presence.publish_heartbeat(self._wall_time())

    def vessel_states(self) -> Dict[str, Dict[str, bool]]:
        """By agent id, what each vessel still lacks before the run may start. A vessel its own software steers is never armed from here."""
        states: Dict[str, Dict[str, bool]] = {}
        for agent_id, client in self.clients.items():
            state = {CONNECTED: bool(client.is_connected), POSITION: bool(client.position_received)}
            if not client.on_board_control_mode:
                state[ARMABLE] = bool(client.is_armable)
            state[AT_START] = bool(client.position_received and client.at_start_point())
            states[agent_id] = state
        return states

    @property
    def is_ready(self) -> bool:
        """Every vessel is connected, reports its position, is at its start point and, when commanded, armable."""
        states = self.vessel_states()
        return bool(states) and all(all(state.values()) for state in states.values())

    @property
    def current_scene(self) -> ConcreteScene:
        """The initial scene with every vessel where its agent reports it (static obstacles stay where they are)."""
        initial = self.trajectories.initial_scene
        reported = {client.actor.id: client.current_agent_state for client in self.clients.values() if client.position_received}
        return ConcreteScene({actor: reported.get(actor.id, initial[actor]) for actor in initial.actors})

    def run(self, on_scene: SceneObserver, stop: threading.Event) -> Optional[ArduAgentRun]:
        """Start every vessel and follow the scenario clock to the trajectories' time span. Blocks.

        Returns the observed run, or None for a run that was stopped. VesselsNotReady when the vessels are not ready.
        """
        if not self.is_ready:
            raise VesselsNotReady("the vessels are not ready to start")
        dt = float(self.trajectories.time_step)
        steps = int(round(self.trajectories.timespan / dt))
        self._start_vessels()
        while not self._commanded_running():
            if not self._pause(stop):
                return None
        started = self._clock()
        origins = {agent_id: client.clock for agent_id, client in self.clients.items() if client.clock > 0}
        run = ArduAgentRun(vessel_ids=[client.actor.id for client in self.clients.values()])
        self._record(run, 0, dt, on_scene)
        index = 0
        ended_early = False
        while index < steps:
            if not self._commanded_running():
                ended_early = True
                break
            elapsed = min(self._elapsed(agent_id, client, origins, started) for agent_id, client in self.clients.items())
            while index < steps and (index + 1) * dt <= elapsed:
                index += 1
                self._record(run, index, dt, on_scene)
            if index < steps and not self._pause(stop):
                return None
        run.run_record = self._run_record(run, dt, ended_early, sorted(set(self.clients) - set(origins)))
        return run

    def _pause(self, stop: threading.Event) -> bool:
        """One poll interval; False when the run was asked to stop."""
        if stop.is_set():
            return False
        self.heartbeat()
        self._sleep(self.POLL_INTERVAL_S)
        return not stop.is_set()

    def _elapsed(self, agent_id: str, client: Any, origins: Dict[str, float], started: float) -> float:
        """The time a vessel has advanced since the start: on its own clock when it reported one at the start, else on the wall clock."""
        if agent_id in origins:
            return float(client.clock) - origins[agent_id]
        return self._clock() - started

    def _start_vessels(self) -> None:
        for client in self.clients.values():
            if client.on_board_control_mode:
                continue
            max_speed = self.trajectories.get_max_speed(client.actor)
            if client.external_control_mode:
                goal = client.mission_waypoints[-1]
                client.publish_go_to(np.array([goal["latitude"], goal["longitude"]]), max_speed)
            else:
                client.publish_follow_path(client.mission_waypoints, max_speed)

    def _commanded_running(self) -> bool:
        """Every vessel that was sent a task is executing it; a vessel its own software steers is not asked."""
        return all(client.execution_state == ExecutionState.RUNNING for client in self.clients.values() if not client.on_board_control_mode)

    def _record(self, run: ArduAgentRun, index: int, dt: float, on_scene: SceneObserver) -> None:
        scene = self.current_scene
        by_id = {actor.id: scene[actor] for actor in scene.actors}
        run.states.append([by_id[vessel_id] for vessel_id in run.vessel_ids])
        on_scene(index * dt, scene)

    def _run_record(self, run: ArduAgentRun, dt: float, ended_early: bool, wall_clock_vessels: List[str]) -> Dict[str, Any]:
        tier = self.resolution.repeatability_tier
        record: Dict[str, Any] = {
            "stack": sorted({str(vessel.stack) for vessel in self.simulation.vessels.values()}),
            "specs": list(dict.fromkeys(spec.id for chain in self.resolution.chains.values() for spec in chain.specs)),
            "dt": dt,
            "steps": run.steps,
            "speedup": self.simulation.speedup,
            "run_seed": self.simulation.environment.seed,
            "repeatability_tier": tier.value if tier is not None else None,
            "environment": self.resolution.effective_environment(),
            "state_digest": run.state_digest(),
            "broker": f"{self.mqtt_connection.client_broker}:{self.mqtt_connection.port}",
            "vessel_topics": {agent_id: vessel.require_connection().topic for agent_id, vessel in self.simulation.vessels.items()},
            "real_vessels": sorted(agent_id for agent_id, vessel in self.simulation.vessels.items() if not vessel.is_simulated),
        }
        if ended_early:
            record["ended_early"] = True
        if wall_clock_vessels:
            record["wall_clock_vessels"] = wall_clock_vessels
        return record
