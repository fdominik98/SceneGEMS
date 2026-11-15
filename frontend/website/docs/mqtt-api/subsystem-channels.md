---
title: Subsystem channels
---

# Subsystem channels

Every subsystem is one service agent with a pool of tasks. The channels on this page are the same for all of them; a subsystem's own page names its task, its signals and its streams.

`<base>` is the subsystem's base topic, `<root>/service/virtual/real/<name>` (see [Overview](./)). PUB and SUB are from the subsystem's point of view: it publishes on a PUB channel and listens on a SUB channel.

## Channels

| Operation | Topic | Message | When |
|-----------|-------|---------|------|
| PUB | `<base>/heartbeat` | [Heartbeat](#heartbeat) | Once a second |
| PUB | `<base>/sensor/sensor_info` | [Sensor info](#sensor-info) | Once a second |
| PUB | `<base>/direct_execution` | [Direct execution info](#direct-execution-info) | Once a second |
| SUB | `<base>/exec/command` | [Start task](#start-task) | A request |
| SUB | `<base>/exec/command` | [Signal task](#signal-task) | A cancel, or a signal of the subsystem's own |
| PUB | `<base>/exec/response` | [Task response](#task-response) | Every state a task goes through |
| PUB | `<base>/exec/feedback` | [Task feedback](#task-feedback) | Progress of a running task |
| PUB | `<base>/sensor/<stream>` | [Stream message](#stream-message) | Previews and results of a task |

Every channel has QoS 1 and retain false.

## Task states

A request becomes one task. A task is in one state at a time, and every change is published on `exec/response`.

| State | Meaning | Final |
|-------|---------|-------|
| `received` | The subsystem took the request and made the task | no |
| `queued` | The task waits for a free place in the pool, or for an earlier task it must not run beside | no |
| `running` | A worker process runs the task | no |
| `finished` | The task ended and published its result | yes |
| `failed` | The task ended without a result; `fail-reason` says why | yes |
| `aborted` | The task was cancelled, queued or running | yes |

| From | Event | To |
|------|-------|----|
| none | `start-task` with the subsystem's task name | `received`, then `queued` |
| none | `start-task` the subsystem cannot run | `failed`, with the reason; the request is never queued |
| `queued` | A place in the pool is free | `running` |
| `queued` | `cancel` signal | `aborted` |
| `running` | The worker returns | `finished` |
| `running` | The worker raises, or its process dies | `failed` |
| `running` | `cancel` signal | `aborted` |

The pool has a fixed number of places (`pool-size` in the direct execution info). A worker node shows them as the slots of the job type.

## Seeds

Every task has a seed, and every response says which. A request that names no seed gets one drawn by the subsystem, between 0 and 2147483647. With the same inputs and the same seed a request gives the same result, wherever a subsystem draws at random.

## Liveness

A requester counts a subsystem as gone when its last heartbeat is older than 5 seconds. The worker node daemon waits for a heartbeat before it sends a request, and fails a job as retryable when the heartbeat stops while the task runs.

## Heartbeat

**PUB** `<base>/heartbeat`

The declaration every WARA-PS agent makes: the subsystem is alive, and what it is.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | The subsystem's name on the broker |
| `agent-type` | string | Always `virtual` |
| `agent-description` | string | Which subsystem it is, such as `Scene Generation Subsystem` |
| `agent-uuid` | string | A UUID drawn when the subsystem started |
| `levels` | string[] | `["sensor", "direct execution"]` |
| `rate` | number | Declarations per second: `1.0` |
| `stamp` | number | Seconds since the Unix epoch |
| `type` | string | `HeartBeat` |

```json
{
  "name": "scene-generation-subsystem-2",
  "agent-type": "virtual",
  "agent-description": "Scene Generation Subsystem",
  "agent-uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "levels": ["sensor", "direct execution"],
  "rate": 1.0,
  "stamp": 1794650475.108,
  "type": "HeartBeat"
}
```

## Sensor info

**PUB** `<base>/sensor/sensor_info`

The streams the subsystem's tasks publish on. Each entry of `sensor-data-provided` is a topic `<base>/sensor/<stream>`.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | The subsystem's name |
| `rate` | number | `1.0` |
| `sensor-data-provided` | string[] | The subsystem's streams |
| `stamp` | number | Seconds since the Unix epoch |
| `type` | string | `SensorInfo` |

```json
{
  "name": "scene-generation-subsystem-2",
  "rate": 1.0,
  "sensor-data-provided": ["generated_scene"],
  "stamp": 1794650475.108,
  "type": "SensorInfo"
}
```

## Direct execution info

**PUB** `<base>/direct_execution`

The requests the subsystem takes, and what its pool holds right now.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | The subsystem's name |
| `rate` | number | `1.0` |
| `type` | string | `DirectExecutionInfo` |
| `stamp` | number | Seconds since the Unix epoch |
| `tasks-available` | object[] | Per request the subsystem takes: its `name` and its `signals` (`cancel` first, then the subsystem's own) |
| `tasks-executing` | object[] | The running tasks: `name` and `uuid` (the task-uuid) |
| `tasks-queued` | object[] | The waiting tasks: `name` and `uuid` |
| `pool-size` | integer | How many tasks run at once |

```json
{
  "name": "monitoring-subsystem-2",
  "rate": 1.0,
  "type": "DirectExecutionInfo",
  "stamp": 1794650475.108,
  "tasks-available": [{"name": "monitor-scenario", "signals": ["cancel", "scenes", "close"]}],
  "tasks-executing": [{"name": "monitor-scenario", "uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678"}],
  "tasks-queued": [],
  "pool-size": 4
}
```

## Start task

**SUB** `<base>/exec/command`

A request. The inputs are in `task.params`, next to the request id and the seed.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | `start-task` |
| `execution-unit` | string | yes | The name of the subsystem the request is for. A command for another name is ignored. |
| `task-uuid` | string | yes | A UUID the requester draws for the task |
| `task.name` | string | yes | The subsystem's task name. A command with another task name is ignored. |
| `task.params` | object | yes | The subsystem's inputs, with the two fields below |
| `task.params.request-id` | string | yes | What the requester tells its requests apart by. Every message about the task carries it, and a signal names it. The worker node daemon uses the job id and the attempt, `<job id>-<attempt>`. |
| `task.params.seed` | integer | no | The task's seed. Drawn by the subsystem when it is left out or null. |
| `task_sender` | string | no | The requester's name |
| `stamp` | number | no | Seconds since the Unix epoch |

```json
{
  "stamp": 1794650475.108,
  "task_sender": "pool_client",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "command": "start-task",
  "execution-unit": "scene-generation-subsystem-2",
  "task": {
    "name": "generate-scene",
    "params": {
      "request-id": "job-7c1d2e90-1",
      "seed": 1234
    }
  }
}
```

A request without a `task-uuid` or a `request-id`, or with inputs the subsystem cannot run, is answered with one `failed` response that says why.

## Signal task

**SUB** `<base>/exec/command`

A signal for the tasks of one request, queued or running. `cancel` is taken by every subsystem; the others are the subsystem's own and are listed on its page and in its direct execution info.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | `signal-task` |
| `execution-unit` | string | yes | The name of the subsystem |
| `signal.name` | string | yes | `cancel`, or a signal of the subsystem |
| `signal.request-id` | string | yes | The request whose tasks get the signal. A signal that names no request is ignored. |
| `signal.data` | any | no | What the signal carries; `cancel` carries nothing |
| `task-uuid` | string | no | A UUID of the command itself, not of the task it addresses |
| `task_sender` | string | no | The sender's name |
| `stamp` | number | no | Seconds since the Unix epoch |

```json
{
  "stamp": 1794650480.412,
  "task_sender": "pool_client",
  "task-uuid": "9c8b7a6f-5e4d-4c3b-9a19-8f7e6d5c4b3a",
  "command": "signal-task",
  "execution-unit": "scene-generation-subsystem-2",
  "signal": {"name": "cancel", "request-id": "job-7c1d2e90-1"}
}
```

A cancel for a request the pool does not hold, and a signal with a name the subsystem does not know, change nothing and get no answer.

## Task response

**PUB** `<base>/exec/response`

One message per state of a task (see [Task states](#task-states)).

| Field | Type | Description |
|-------|------|-------------|
| `stamp` | number | Seconds since the Unix epoch |
| `task_sender` | string | The subsystem's name. A requester takes only the messages of the subsystem it asked. |
| `task-uuid` | string | The task-uuid of the request |
| `request-id` | string | The request id of the request |
| `response` | string | `received`, `queued`, `running`, `finished`, `failed` or `aborted` |
| `fail-reason` | string or null | Why the task failed; null otherwise |
| `seed` | integer or null | The task's seed; null for a request that was refused |

```json
{
  "stamp": 1794650475.311,
  "task_sender": "scene-generation-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-7c1d2e90-1",
  "response": "running",
  "fail-reason": null,
  "seed": 1234
}
```

## Task feedback

**PUB** `<base>/exec/feedback`

Progress of a running task. Not every subsystem reports progress; the page of a subsystem says what its `detail` holds.

| Field | Type | Description |
|-------|------|-------------|
| `stamp` | number | Seconds since the Unix epoch |
| `task_sender` | string | The subsystem's name |
| `task-uuid` | string | The task-uuid of the request |
| `request-id` | string | The request id of the request |
| `status` | string | Always `running` |
| `message` | string | What the task is doing, for a person to read |
| `progress` | number or null | The fraction done, 0 to 1, when the task knows it |
| `detail` | object or null | The subsystem's own fields |

```json
{
  "stamp": 1794650478.02,
  "task_sender": "design-space-exploration-subsystem-1",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-51aa0c3d-1",
  "status": "running",
  "message": "generating models",
  "progress": null,
  "detail": {"phase": "generating", "models_found": 12}
}
```

## Stream message

**PUB** `<base>/sensor/<stream>`

What a task produces: previews while it works, and its result. Every stream message starts with the four fields below; the rest is the subsystem's own and is described on its page.

| Field | Type | Description |
|-------|------|-------------|
| `stamp` | number | Seconds since the Unix epoch |
| `task_sender` | string | The subsystem's name |
| `task-uuid` | string | The task-uuid of the request |
| `request-id` | string | The request id of the request |

Most streams also carry `final`: true on the task's last message on that stream, which is its result, and false on the messages before it. A task that was cancelled publishes no result unless its page says so.
