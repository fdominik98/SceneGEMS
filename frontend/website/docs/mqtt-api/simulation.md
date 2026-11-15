---
title: Simulation MQTT API
sidebar_label: Simulation
---

# Simulation subsystem

Runs a scenario on the vessel stacks of its vessels. A `run-simulation` request is one task: one run, with a stack of its own (one simulator for the scenario and, per vessel, a controller and an ASV system). The subsystem is the only one that starts containers: it brings the run's stack up, follows the run and removes the stack. Different requests run side by side, as many as the pool has places.

The subsystem takes a second request, `compare-repeats`: how far the finished repeats of one run on one stack drift apart. It starts no container.

| Property | Value |
|----------|-------|
| Name | `simulation-subsystem`, on a worker node `simulation-subsystem-<n>` |
| Base topic | `<root>/service/virtual/real/<name>` |
| Tasks | `run-simulation`, `compare-repeats` |
| Signals | `cancel`, `observe`, `start` |
| Streams | `simulation_frames`, `simulation_log`, `simulation_result` |

The heartbeat, the declarations, the command envelope and the task states are in [Subsystem channels](./subsystem-channels).

## Channels

| Operation | Topic | Message |
|-----------|-------|---------|
| SUB | `<base>/exec/command` | [run-simulation](#run-simulation) |
| SUB | `<base>/exec/command` | [compare-repeats](#compare-repeats) |
| SUB | `<base>/exec/command` | [observe signal](#observe-signal) |
| SUB | `<base>/exec/command` | [start signal](#start-signal) |
| PUB | `<base>/exec/feedback` | [Run status](#run-status) |
| PUB | `<base>/sensor/simulation_frames` | [Simulation frames](#simulation-frames) |
| PUB | `<base>/sensor/simulation_log` | [Simulation log](#simulation-log) |
| PUB | `<base>/sensor/simulation_result` | [Simulation result](#simulation-result) |
| PUB | `<root>/service/virtual/real/<monitoring subsystem>/exec/command` | A `cancel` for the series of a judged run (see [Monitoring](./monitoring#series-of-a-run-that-is-judged-while-it-runs)) |

## run-simulation

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. The seed is the run seed of the payload.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `job-id` | string | yes | The job the run belongs to. The run's containers and frames are named after it. Not empty. |
| `attempt` | integer | no | The job's attempt, at least 1, so a retry never meets what an earlier one left. 1 when left out. |
| `payload` | object | yes | The payload of the simulation job. It names its runner under `runner`; the other fields are that runner's. |

| `payload.runner` | What runs |
|------------------|-----------|
| `kinematic` | Replay, USV Navigation or MOOS-IvP on the kinematic layer |
| `ardupilot` | Replay, USV Navigation or MOOS-IvP on an ArduPilot SITL or Gazebo stack, in lockstep over MAVLink |
| `gazebo_custom` | Replay, USV Navigation or MOOS-IvP on the custom controller, stepping a Gazebo world |
| `attended` | The workbench's setup vessel by vessel, with an operator beside it: it waits for a `start` signal, and Mission Planner or a real vessel may take part |

The fields most runners share: `trajectories` (the trajectories to run, inline or as a reference to an artifact), `mode`, `own_ship_id`, `seed`, `monitor` (`none` or `live`), `colregs_constraints_content`, `include_trajectories` and `timeout_s`. The payload has the snake case names of the cluster's job protocol, not the kebab case of the envelope.

```json
{
  "stamp": 1794650475.108,
  "task_sender": "pool_client",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "command": "start-task",
  "execution-unit": "simulation-subsystem-2",
  "task": {
    "name": "run-simulation",
    "params": {
      "job-id": "4f6c0a1e-77b2-4d0c-b1a9-3e5d2c8f9a10",
      "attempt": 1,
      "payload": {"runner": "kinematic", "mode": "replay", "trajectories": {}, "monitor": "live", "seed": 3},
      "request-id": "4f6c0a1e-77b2-4d0c-b1a9-3e5d2c8f9a10-1",
      "seed": 3
    }
  }
}
```

## compare-repeats

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. Nothing is drawn at random; the seed is carried for the record. The task takes no signal but `cancel`, reports its progress on `exec/feedback` and publishes its result on `simulation_result`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `payload.trajectories` | object[] | yes | The repeats of one case on one stack, at least two, each inline or a reference to an artifact |
| `payload.reference` | string | yes | The name of the reference scenario or case |
| `payload.stack` | object | no | A free description of the stack and the release, returned as given |
| `payload.timeout_s` | number | no | The comparison's time limit in seconds. 600 when left out. |

## observe signal

**SUB** `<base>/exec/command`

Somebody watches the run, or stopped watching. Frames are published only while a run is observed. The fields of `signal.data`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `active` | boolean | no | Whether the run is watched. False when left out. |
| `speed` | number | no | The speed it is watched at, in times real time. 1 when left out. |

```json
{
  "stamp": 1794650480.412,
  "task_sender": "pool_client",
  "task-uuid": "9c8b7a6f-5e4d-4c3b-9a19-8f7e6d5c4b3a",
  "command": "signal-task",
  "execution-unit": "simulation-subsystem-2",
  "signal": {
    "name": "observe",
    "request-id": "4f6c0a1e-77b2-4d0c-b1a9-3e5d2c8f9a10-1",
    "data": {"active": true, "speed": 4}
  }
}
```

## start signal

**SUB** `<base>/exec/command`

The operator's Start of an attended run. It carries no data. An attended run brings its stack up, reports the phase `ready_to_start` and waits for this signal; the wait does not count against the run's time.

## Run status

**PUB** `<base>/exec/feedback`

The status of the run, whenever it changes.

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | What the run is doing |
| `progress` | number or null | The fraction of the run that is done, 0 to 1 |
| `detail.phase` | string | Attended runs only: `preparing` (the stack is coming up), `ready_to_start` (it waits for the `start` signal) or `running` |
| `detail.vessels` | object | Runs with a real vessel only: per agent id, whether the vessel is `connected`, reports its `position`, is `armable` and is `at_start` |
| `detail.ground_control` | object | Mission Planner vessels only: per agent id, the port on the worker node's host a ground control station connects to |

```json
{
  "stamp": 1794650483.0,
  "task_sender": "simulation-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "4f6c0a1e-77b2-4d0c-b1a9-3e5d2c8f9a10-1",
  "status": "running",
  "message": "ready to start",
  "progress": null,
  "detail": {
    "phase": "ready_to_start",
    "vessels": {
      "0": {"connected": true, "position": true, "armable": true, "at_start": true},
      "1": {"connected": true, "position": true, "armable": true, "at_start": true}
    }
  }
}
```

## Simulation frames

**PUB** `<base>/sensor/simulation_frames`

The frames of an observed run, in batches.

| Field | Type | Description |
|-------|------|-------------|
| `index` | integer | The batch's number, from 0 |
| `frames` | object[] | The frames of the batch in time order (see [Message conventions](./#message-conventions)) |
| `final` | boolean | Always false |

## Simulation log

**PUB** `<base>/sensor/simulation_log`

The lines the run's containers wrote, in batches of at most 200 lines.

| Field | Type | Description |
|-------|------|-------------|
| `index` | integer | The batch's number, from 0 |
| `lines` | object[] | Per line its `source` (the container), its `text` and its `stream` (`stdout` or `stderr`) |
| `final` | boolean | Always false |

## Simulation result

**PUB** `<base>/sensor/simulation_result`

One message at the end of a run or of a comparison. A run that fails with a reason (a stack the worker node cannot run, a runner that reported an error, nobody started it in time) is a result too: the requester has to hear the reason and whether another attempt can succeed. A cancelled task publishes no result.

| Field | Type | Description |
|-------|------|-------------|
| `result` | object or null | The result as the simulation job returns it: the run record, the state digest, the monitor's summary and the simulated trajectories. For `compare-repeats`, the comparison. Null for a run that failed. |
| `error` | string or null | Why the run failed |
| `retryable` | boolean | Whether another attempt can succeed |
| `frame-batches` | integer | How many frame batches went before the result |
| `log-batches` | integer | How many log batches went before the result |
| `final` | boolean | Always true |

```json
{
  "stamp": 1794650560.8,
  "task_sender": "simulation-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "4f6c0a1e-77b2-4d0c-b1a9-3e5d2c8f9a10-1",
  "result": null,
  "error": "Simulation stack rejected: <reason>",
  "retryable": false,
  "frame-batches": 0,
  "log-batches": 3,
  "final": true
}
```

## Runs with a real vessel

An attended run with a real vessel drives every vessel through its agent over MQTT. For that run the runner container is on the broker too: it publishes a heartbeat as a service agent under the name the vessels' commands carry as their `sender`, and it is the commander of the vessel agents. The channels it uses are on the [Vessels](./vessels) page.
