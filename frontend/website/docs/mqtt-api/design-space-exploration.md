---
title: Design space exploration MQTT API
sidebar_label: Design space exploration
---

# Design space exploration subsystem

Finds every functional equivalence class (FEC) of a specification within a scope, with the Refinery model generator. A request is one task: the whole exploration, which cannot be split. Different requests run side by side, as many as the pool has places.

| Property | Value |
|----------|-------|
| Name | `design-space-exploration-subsystem`, on a worker node `design-space-exploration-subsystem-<n>` |
| Base topic | `<root>/service/virtual/real/<name>` |
| Task | `explore-design-space` |
| Signals | `cancel` |
| Streams | `design_space` |

The heartbeat, the declarations, the command envelope and the task states are in [Subsystem channels](./subsystem-channels).

## Channels

| Operation | Topic | Message |
|-----------|-------|---------|
| SUB | `<base>/exec/command` | [explore-design-space](#explore-design-space) |
| PUB | `<base>/exec/feedback` | [Exploration progress](#exploration-progress) |
| PUB | `<base>/sensor/design_space` | [Design space](#design-space) |

## explore-design-space

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. The seed is the generator's random seed: it fixes the order the FECs are found in.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `problem` | string | yes | Refinery source: the specification, and the scope when `scopes` does not give it. Not empty. |
| `scopes` | string[] | no | Scope entries in the generator's form, such as `TS=2` or `TS=1..3` |
| `scope-overrides` | string[] | no | Entries that replace the problem's scope of the same class |
| `max-models` | integer | no | The most FECs to generate, at least 1. Every FEC when left out. |
| `timeout` | number | no | The generation's time limit in seconds, above 0. None when left out. |
| `load-timeout` | number | no | Seconds the generator may take to load the problem, above 0. 120 when left out. |
| `state-coder-depth` | integer | no | Neighbourhood depth for telling models apart, at least 1. Refinery's default when left out. |
| `status-interval` | number | no | Seconds between two progress messages, above 0. 1 when left out. |

A field that is not in this table is refused, as the generator itself would refuse it, so a misspelled limit is never ignored.

```json
{
  "stamp": 1794650475.108,
  "task_sender": "pool_client",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "command": "start-task",
  "execution-unit": "design-space-exploration-subsystem-1",
  "task": {
    "name": "explore-design-space",
    "params": {
      "problem": "class Vessel { ... }",
      "scopes": ["TS=2", "StaticObstacle=0"],
      "scope-overrides": [],
      "timeout": 600,
      "load-timeout": 120,
      "status-interval": 1,
      "request-id": "job-51aa0c3d-1",
      "seed": 7
    }
  }
}
```

## Exploration progress

**PUB** `<base>/exec/feedback`

One message per status interval while the generator works. `detail` holds the generator's other status fields.

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | The generator's status line |
| `progress` | number or null | The fraction done, when the generator knows it |
| `detail.phase` | string | Where the generator is, such as `loading`, `generating` or `finished` |
| `detail.models_found` | integer | How many FECs it found so far |

## Design space

**PUB** `<base>/sensor/design_space`

One message per task, at its end. A generator error is a result and not a failed task: a specification that does not parse fails the same way at every attempt, and the requester has to hear that. A generator that ends without a result (killed, out of memory, past its limits) fails the task instead.

| Field | Type | Description |
|-------|------|-------------|
| `design-space` | object or null | The explored FECs; null when the generator could not explore |
| `design-space.functional_scenarios` | string[] | The FECs in the order they were found, each as the source of a functional scenario with the catalog's object names (`os`, `ts1`, `obst1`) |
| `design-space.fecs` | object[] | Per FEC its `index`, `vessel_count` and `obstacle_count` |
| `design-space.stop_reason` | string | Why the generation ended, such as `exhausted` or `cap_reached` |
| `design-space.complete` | boolean | Whether every FEC of the scope was found |
| `design-space.models_found` | integer | How many FECs were found |
| `design-space.max_models` | integer or null | The cap of the request |
| `design-space.random_seed` | integer | The seed the generator used |
| `design-space.elapsed_s` | number | The generation's time in seconds |
| `design-space.message` | string or null | The generator's closing message |
| `error` | string or null | Why the generator could not explore: a specification that does not parse, a bad scope |
| `retryable` | boolean | Whether another attempt could end differently |
| `final` | boolean | Always true |

```json
{
  "stamp": 1794650512.77,
  "task_sender": "design-space-exploration-subsystem-1",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-51aa0c3d-1",
  "design-space": {
    "stop_reason": "exhausted",
    "complete": true,
    "models_found": 2,
    "max_models": null,
    "random_seed": 7,
    "elapsed_s": 1.5,
    "message": null,
    "fecs": [
      {"index": 0, "vessel_count": 3, "obstacle_count": 0},
      {"index": 1, "vessel_count": 3, "obstacle_count": 0}
    ],
    "functional_scenarios": ["...", "..."]
  },
  "error": null,
  "retryable": false,
  "final": true
}
```

A cancelled exploration ends its generator at once and publishes nothing on the stream.
