---
title: Vessel MQTT API
sidebar_label: Vessels
---

# Vessels

A vessel is on the broker through its agent, ArduAgent: a WARA-PS unit agent beside the vessel's ArduPilot autopilot. It publishes the vessel's telemetry and takes its tasks, as the WARA-PS [Declarations](https://waraps.org/docs/asyncapi/waraps-api-declarations/waraps-api-declarations), [Sensors](https://waraps.org/docs/asyncapi/waraps-api-sensors/waraps-api-sensors) and [Tasks](https://waraps.org/docs/asyncapi/waraps-api-tasks/waraps-api-tasks) specifications describe them. This page lists the channels a SceneGEMS run uses, the channels the agent adds, and what a run sends.

## Which vessels are on the broker

Only a run with a real vessel uses vessel agents. A real vessel is reached only through the agent on board, so such a run drives every vessel that way:

| Vessel | Agent | Base topic |
|--------|-------|------------|
| Real vessel | The ArduAgent on board | The topic the operator gives for the vessel, such as `waraps/unit/surface/real/<name>` |
| Simulated vessel of the same run | An ArduAgent in the job's stack, beside the vessel's ArduPilot SITL | `<root>/unit/surface/simulation/<vessel>-<job>`, such as `scenegems/unit/surface/simulation/ts1-4f6c0a1e` |

A run of simulated vessels only does not use MQTT for its vessels: the runner steps the simulator and talks to every vessel's controller in lockstep (the kinematic layer, MAVLink to ArduPilot SITL, the custom controller, USV Navigation and MOOS-IvP).

The broker is the cluster broker (root `scenegems`) unless the run names an external one (root `waraps`); see [Connections](../connections). On an external broker a vessel's topics are the ones the WARA-PS map and other WARA-PS agents use.

`<base>` is the agent's base topic. PUB and SUB are from the agent's point of view.

## Channels

| Operation | Topic | Message | Used by a run |
|-----------|-------|---------|---------------|
| PUB | `<base>/heartbeat` | [Heartbeat](#declarations) | no |
| PUB | `<base>/sensor_info` | [Sensor info](#declarations) | no |
| PUB | `<base>/direct_execution_info` | [Direct execution info](#declarations) | no |
| PUB | `<base>/sensor/position` | [Position](#sensors) | yes |
| PUB | `<base>/sensor/heading` | [Heading](#sensors) | yes |
| PUB | `<base>/sensor/speed` | [Speed](#sensors) | yes |
| PUB | `<base>/sensor/armable` | [Armable](#sensors) | yes |
| PUB | `<base>/sensor/clock` | [Clock](#sensors) | yes |
| PUB | `<base>/sensor/<other>` | [Other sensors](#sensors) | no |
| SUB | `<base>/exec/command` | [move-path](#move-path), [move-to](#move-to), [other commands](#other-commands) | yes |
| PUB | `<base>/exec/response` | [Task response](#task-response) | yes |
| PUB | `<base>/exec/feedback` | [Task feedback](#task-feedback) | no |
| SUB | `<root>/unit/+/+/+/sensor/position` | [Positions of other agents](#positions-of-other-agents) | no |
| SUB | `<base>/sensor/rc_override` | [RC override](#rc-override) | no |
| SUB | `<base>/sensor/obstacle_distances` | [Obstacle distances](#obstacle-distances) | no |

The agent publishes with QoS 0 and retain false. It takes commands with QoS 1 and everything else with QoS 0.

## Topics of an agent

The agent derives its topics from its environment:

| Variable | Meaning | Default |
|----------|---------|---------|
| `MQTT_TOPIC_ROOT` | The first topic level | `waraps` |
| `DOMAIN` | The domain level, and the agent type of the heartbeat | none; `surface` for a vessel |
| `REAL_SIM` | `real` or `simulation` | none |
| `NAME` | The agent's name | none |
| `BASE_TOPIC` | Replaces the whole base topic | `<root>/unit/<domain>/<real or simulation>/<name>` |
| `OTHER_POSITIONS_TOPIC` | Replaces the filter for other agents' positions | `<root>/unit/+/+/+/sensor/position` |
| `OTHER_POSITIONS_TOPICS` | The position topics of the agents whose positions are taken, separated by commas and without wildcards. Wins over `OTHER_POSITIONS_TOPIC`. | none |

A simulated vessel of a job is given the position topics of the other vessels of its own run in `OTHER_POSITIONS_TOPICS`, so two runs on one broker never see each other.

## Declarations

**PUB** `<base>/heartbeat`, `<base>/sensor_info`, `<base>/direct_execution_info`

The three WARA-PS declarations, every 2 seconds.

```json
{
  "name": "ts1-4f6c0a1e",
  "agent-uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "agent-type": "surface",
  "agent-description": "surface vessel",
  "agent-model": "usv.mini_usv",
  "levels": ["sensor", "direct execution", "tst execution"],
  "rate": 0.5,
  "stamp": 1794650475.108,
  "type": "HeartBeat"
}
```

The sensor info lists `position`, `speed`, `course`, `heading`, `mode`, `state`, `waypoints`, `energy_level`, `battery_status`, `cargo`, `control_system_version` and `clock`, and `videoserver_url` when the agent has a video server.

The direct execution info lists the tasks `move-to`, `move-path`, `go-home`, `search-area`, `set-heading-thrust` and `follow-lead` with the signals `$abort`, `$enough`, `$continue` and `$pause`, `collect` and `release` with `$abort`, and `set-geofence` and `add-no-go-zone` without signals. Its `tasks-executing` is always empty.

## Sensors

**PUB** `<base>/sensor/<name>`

| Channel | Payload | Description | Used by a run |
|---------|---------|-------------|---------------|
| `position` | object | `latitude` and `longitude` in WGS84 degrees, `altitude` in metres | The vessel's position, converted to the scenario's local frame |
| `heading` | number | Degrees from true north | The vessel's heading |
| `speed` | number | Speed over ground in metres per second | The vessel's speed |
| `armable` | `True` or `False` | Whether the autopilot can be armed | A commanded vessel must be armable before a run starts |
| `clock` | number | The autopilot's `SYSTEM_TIME` in seconds since the Unix epoch. Not in the WARA-PS API. | The scenario clock of the run |
| `course` | number | Course over ground in degrees from north | |
| `waypoints` | object[] | The mission's remaining waypoints as `GeoPoint` objects | |
| `mode` | string | The autopilot's mode in lower case, such as `auto` or `manual` | |
| `state` | string | The arming state in lower case | |
| `energy_level` | number | Energy as a percentage of full | |
| `battery_status` | object | Voltage, current and level | |
| `cargo` | object[] | The collected items, each with its `name` | |
| `control_system_version` | string | The autopilot's version | |
| `ipaddress` | string | The agent's local address | |
| `videoserver_url` | string | Where the agent's camera feed is restreamed | |
| `speed_preset` | object | The autopilot's speed presets. Not in the WARA-PS API. | |
| `info` | string | Free text of the agent. Not in the WARA-PS API. | |

```json
{"latitude": 57.7611363, "longitude": 16.6805011, "altitude": 0.0}
```

The run reads the scenario clock from `clock`: the time every vessel has advanced since the start, so the clock slows down with the simulators. A vessel that reports no clock is taken on the wall clock, which is the clock of a real vessel.

## move-path

**SUB** `<base>/exec/command`

Follow a path of waypoints. A run sends it once, at its start, to every vessel that replays its trajectory: the trajectory as a mission.

| Field | Type | Description |
|-------|------|-------------|
| `command` | string | `start-task` |
| `com-uuid` | string | A UUID of the command |
| `task-uuid` | string | A UUID of the task; the responses carry it |
| `execution-unit` | string | The agent's name |
| `sender` | string | The name of the run's simulation subsystem on the broker |
| `task.name` | string | `move-path` |
| `task.params.waypoints` | object[] | The path: `GeoPoint` objects with `latitude`, `longitude` and `altitude`. A surface vessel ignores the altitude. |
| `task.params.speed` | string | The vessel's highest speed on the trajectory, in metres per second. The agent also takes the WARA-PS presets such as `standard`. |
| `task.params.loop` | boolean or integer | Whether to repeat the path. A run sends false. |

```json
{
  "com-uuid": "2b3c4d5e-6f70-4819-9abc-def012345679",
  "command": "start-task",
  "execution-unit": "ts1-4f6c0a1e",
  "sender": "simulation-subsystem-2",
  "task": {
    "name": "move-path",
    "params": {
      "speed": "5.1",
      "waypoints": [
        {"latitude": 57.7611363, "longitude": 16.6805011, "altitude": 0, "rostype": "GeoPoint"},
        {"latitude": 57.7634512, "longitude": 16.6841207, "altitude": 0, "rostype": "GeoPoint"}
      ],
      "loop": false
    }
  },
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "time_added": 0
}
```

## move-to

**SUB** `<base>/exec/command`

Move to one position. A run sends it once, at its start, to a vessel Mission Planner steers: toward the last waypoint of its trajectory, and the rest is left to the operator.

The envelope is the one of `move-path`. The fields of `task.params`:

| Field | Type | Description |
|-------|------|-------------|
| `waypoint` | object | A `GeoPoint`: `latitude`, `longitude`, `altitude` and `rostype` |
| `speed` | string | As for `move-path` |

## What a run sends

| ASV system of the vessel | Control mode | Command at the start |
|--------------------------|--------------|----------------------|
| Replay | autonomous | `move-path` with the trajectory as a mission |
| Mission Planner | external | `move-to` toward the last waypoint |
| On-board software | on_board | Nothing: the vessel's own software steers, and the agent only reports where it is |

Before the run may start, every vessel must be connected, report its position, be at the point the scenario starts it from and, when it is commanded, be armable. Until then the run's status says what each vessel lacks (see [Run status](./simulation#run-status)).

Nothing is sent to a vessel when a run ends or is stopped: it finishes its task on its own. A run sends no signal.

## Other commands

**SUB** `<base>/exec/command`

The agent takes the other tasks and signals of the WARA-PS Tasks API; a SceneGEMS run sends none of them.

| Command | Values |
|---------|--------|
| `start-task` | `go-home`, `search-area`, `follow-lead`, `collect`, `release`, `set-speed`, `reset-speed`, `set-geofence`, `add-no-go-zone`, `set-heading-thrust` |
| `signal-task` | `signal` is `$abort`, `$enough`, `$pause` or `$continue` |
| `ping` | Answered with the response `pong`. Not in the WARA-PS API. |

## Task response

**PUB** `<base>/exec/response`

| Field | Type | Description |
|-------|------|-------------|
| `agent-uuid` | string | The agent's UUID |
| `com-uuid` | string | A UUID of the response |
| `response` | string | `running` when the command arrived, then `finished`, `failed` or `aborted` |
| `fail-reason` | string | Why the command failed, such as `Not ready - Pre tests`, `Not armed - Manual` or `Occupied`; empty otherwise |
| `response-to` | string | The `com-uuid` of the command |
| `task-uuid` | string | The `task-uuid` of the command |

A run takes a vessel as running once the response to its task is `running`, and as stopped once it is `finished`, `failed` or `aborted`. The run ends at the trajectories' time span, or earlier when the commanded vessels stop.

```json
{
  "agent-uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "com-uuid": "9c8b7a6f-5e4d-4c3b-9a19-8f7e6d5c4b3a",
  "fail-reason": "",
  "response": "running",
  "response-to": "2b3c4d5e-6f70-4819-9abc-def012345679",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678"
}
```

## Task feedback

**PUB** `<base>/exec/feedback`

| Field | Type | Description |
|-------|------|-------------|
| `agent-uuid` | string | The agent's UUID |
| `com-uuid` | string | A UUID of the feedback |
| `status` | string | `starting`, `planning`, `running`, `paused`, `finished`, `failed` or `aborted` |
| `task-uuid` | string | The `task-uuid` of the command |

## Positions of other agents

**SUB** `<root>/unit/+/+/+/sensor/position`, or the topics of `OTHER_POSITIONS_TOPICS`

The agent reads the positions of other agents for its collision avoidance (agents of its own domain and context) and for `follow-lead`. The message is the position message above.

## RC override

**SUB** `<base>/sensor/rc_override`

Sets the two motor channels of the autopilot directly. Not in the WARA-PS API.

| Field | Type | Description |
|-------|------|-------------|
| `left_pwm` | integer or null | Pulse width for the left motor, 1000 to 2000 |
| `right_pwm` | integer or null | Pulse width for the right motor, 1000 to 2000 |

A message with a null value releases the override.

## Obstacle distances

**SUB** `<base>/sensor/obstacle_distances`

Distances to obstacles around the vessel, passed on to the autopilot as a MAVLink `OBSTACLE_DISTANCE` message. Not in the WARA-PS API.

| Field | Type | Description |
|-------|------|-------------|
| `distances` | number[] | The distance per sector |
| `increment` | integer | The angle of a sector in degrees |
| `min_distance` | number | The shortest distance the sensor measures |
| `max_distance` | number | The longest distance the sensor measures |

## What the run publishes beside the commands

| Topic | Message | When |
|-------|---------|------|
| `<root>/service/virtual/real/<name>/heartbeat` | The heartbeat of the run's simulation subsystem, under the name the commands carry as `sender`. Its `levels` is empty. | Once a second while the run is connected |
| `waraps/general/generic/real/c2/target/positions/<vessel>_PATH` | A WARA-PS map object: `name`, `type` `polyline`, `line` (the planned path as latitude and longitude pairs) and `color` | Once per vessel when the run connects, on a broker with the root `waraps` only |

The map object draws every vessel's planned path on the WARA-PS map; see the [WARA-PS Map Objects MQTT API](https://waraps.org/docs/asyncapi/waraps-api-map-objects/waraps-api-map-objects). A control node's own broker has no map, so nothing is published there.
