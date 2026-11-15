---
title: Scene generation MQTT API
sidebar_label: Scene generation
---

# Scene generation subsystem

Searches for one scene of a functional equivalence class (FEC). A request is one task: the search for one scene. Different requests run side by side, as many as the pool has places.

| Property | Value |
|----------|-------|
| Name | `scene-generation-subsystem`, on a worker node `scene-generation-subsystem-<n>` |
| Base topic | `<root>/service/virtual/real/<name>` |
| Task | `generate-scene` |
| Signals | `cancel` |
| Streams | `generated_scene` |

The heartbeat, the declarations, the command envelope and the task states are in [Subsystem channels](./subsystem-channels).

## Channels

| Operation | Topic | Message |
|-----------|-------|---------|
| SUB | `<base>/exec/command` | [generate-scene](#generate-scene) |
| PUB | `<base>/sensor/generated_scene` | [Generated scene](#generated-scene) |

The subsystem publishes nothing on `exec/feedback`: its progress is the scenes on the stream.

## generate-scene

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. The seed seeds every random draw of the search, so it fixes the scene.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `functional-scenario-content` | string | yes | The functional scenario: the source of a FEC specification |
| `colregs-constraints-content` | string | yes | The COLREGS constants, as YAML text |
| `vessel-types-content` | string | yes | The vessel types, as YAML text |
| `obstacle-types-content` | string | yes | The obstacle types, as YAML text |
| `timeout` | number | yes | The search's time limit in seconds |
| `enforce-low-tcpa` | boolean | no | Whether the scene must have a low time to the closest point of approach. False when left out. |

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
      "functional-scenario-content": "...",
      "colregs-constraints-content": "...",
      "vessel-types-content": "...",
      "obstacle-types-content": "...",
      "timeout": 60,
      "enforce-low-tcpa": false,
      "request-id": "job-7c1d2e90-1",
      "seed": 1234
    }
  }
}
```

## Generated scene

**PUB** `<base>/sensor/generated_scene`

While the search runs, its best scene so far once a second, with `final` false. At the end the final scene, with `final` true and whether it satisfies the class. A cancelled search publishes no final scene.

| Field | Type | Description |
|-------|------|-------------|
| `generated-frame` | object | The scene as a frame (see [Message conventions](./#message-conventions)): `scenarioId` is the request id, `timestamp` 0 and `timeStep` 1 |
| `evaluation-data` | object | The record of the search: the scene (`best_scene`), its fitness (`best_fitness`), the seed (`random_seed`), the time it took (`evaluation_time`), the counts of vessels and obstacles, the settings of the search, and `error_message` |
| `valid` | boolean | Whether the scene satisfies every constraint of the class |
| `final` | boolean | True on the task's last scene; the scenes before it are search progress |

```json
{
  "stamp": 1794650481.93,
  "task_sender": "scene-generation-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-7c1d2e90-1",
  "generated-frame": {
    "scenarioId": "job-7c1d2e90-1",
    "timestamp": 0,
    "timeStep": 1,
    "actors": [{"id": "0", "name": "os", "isVessel": true, "isOwnShip": true, "length": 30.0}],
    "statesByActorId": {"0": {"x": 0.0, "y": 0.0, "speed": 5.1, "heading": 1.57}},
    "situationContexts": [],
    "colregsStates": [],
    "ruleResults": [],
    "maneuverStates": [],
    "metrics": {}
  },
  "evaluation-data": {"random_seed": 1234, "best_fitness": [0.0], "evaluation_time": 6.4},
  "valid": true,
  "final": true
}
```

The example shortens the actor and the evaluation data. An actor carries its dimensions and limits (`length`, `breadth`, `mass`, `safetyRadius`, `maxSpeed` and more); a state is a position in metres, a speed in metres per second and a heading in radians.
