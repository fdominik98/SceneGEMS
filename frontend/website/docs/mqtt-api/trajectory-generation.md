---
title: Trajectory generation MQTT API
sidebar_label: Trajectory generation
---

# Trajectory generation subsystem

Plans the trajectories of a scene. A request is one task: one plan for one scene. Different requests run side by side, as many as the pool has places.

| Property | Value |
|----------|-------|
| Name | `trajectory-generation-subsystem`, on a worker node `trajectory-generation-subsystem-<n>` |
| Base topic | `<root>/service/virtual/real/<name>` |
| Task | `generate-trajectories` |
| Signals | `cancel` |
| Streams | `planned_trajectory_preview`, `planned_trajectory` |

The heartbeat, the declarations, the command envelope and the task states are in [Subsystem channels](./subsystem-channels).

## Channels

| Operation | Topic | Message |
|-----------|-------|---------|
| SUB | `<base>/exec/command` | [generate-trajectories](#generate-trajectories) |
| PUB | `<base>/sensor/planned_trajectory_preview` | [Trajectory preview](#trajectory-preview) |
| PUB | `<base>/sensor/planned_trajectory` | [Planned trajectory](#planned-trajectory) |

The subsystem publishes nothing on `exec/feedback`: its progress is the previews.

## generate-trajectories

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. The seed seeds every random draw of the search, so it fixes the plan.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario-content` | string | yes | The scene to plan from, as JSON text: the evaluation data of a generated scene, or an object with the scene under `best_scene`, `scene` or `initial_scene` |
| `colregs-constraints-content` | string | yes | The COLREGS constants, as YAML text |
| `params` | object | no | The tuning values below. Every one of them may be left out or null, which means the planner's default. |

| Field of `params` | Type | Description |
|-------------------|------|-------------|
| `generator` | string | `monitor_driven_rrt`, the monitor-guided planner (the default), or `straight`: every vessel straight on from the scene |
| `time-step` | integer | Seconds between two scenes of the plan |
| `timeout` | number | The search's time limit in seconds |
| `max-iterations` | integer | The most iterations of the search |
| `direction-threshold` | number | The planner's direction threshold |
| `best-random-nodes-k` | integer | How many of the best random nodes the planner keeps |
| `preview-interval` | integer | Iterations between two previews the planner offers |
| `include-monitor-results` | boolean | Whether previews and the result carry the monitor's output for each scene. On unless false. |
| `timespan` | number | `straight` only: the length of the trajectories in seconds, above 0. One hour when left out. |

```json
{
  "stamp": 1794650475.108,
  "task_sender": "pool_client",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "command": "start-task",
  "execution-unit": "trajectory-generation-subsystem-2",
  "task": {
    "name": "generate-trajectories",
    "params": {
      "scenario-content": "{\"best_scene\": {}}",
      "colregs-constraints-content": "...",
      "params": {"generator": "monitor_driven_rrt", "time-step": 1, "timeout": 120, "include-monitor-results": true},
      "request-id": "job-9be04417-1",
      "seed": 1234
    }
  }
}
```

## Trajectory preview

**PUB** `<base>/sensor/planned_trajectory_preview`

The plan as it stands while the search runs, at most one per second. The `straight` generator publishes no preview.

| Field | Type | Description |
|-------|------|-------------|
| `trajectory-data` | object | The plan so far, in the form of the result's `trajectory-data` |

## Planned trajectory

**PUB** `<base>/sensor/planned_trajectory`

One message per task: its result. A search that plans nothing still has a result, with `valid` false and the reason. A search that ends without a whole plan (its time is over, the task was cancelled, a COLREGS failure could not be repaired) returns its best partial path: `valid` true and `complete` false.

| Field | Type | Description |
|-------|------|-------------|
| `trajectory-data` | object or null | The plan; null when there is none |
| `trajectory-data.trajectories` | object | The trajectories: under `scene_list` the scenes of the plan in time order, one per time step |
| `trajectory-data.random_seed` | integer | The seed of the search |
| `trajectory-data.iter_numbers` | object | How many iterations the search took |
| `trajectory-data.overall_eval_time` | number | The search's time in seconds |
| `trajectory-data.monitor_frames` | object[] or object | The monitor's output for each scene of the plan, in the order of the scenes, written without what repeats from scene to scene. For a plan of two scenes or more it is the object `{"encoding": "carry_forward", "encoded_frames": [...]}`: the first entry of `encoded_frames` is the first scene's output whole, and every later entry holds only the sections (`ruleResults`, `situationContexts`, `colregsStates`, `maneuverStates`, `metrics`) that differ from the scene before; a section that is missing is the one of the scene before. There is one entry per scene, an empty object where nothing changed. A plan of one scene, and a result written by an earlier release, has a plain list of one object per scene. Present only when monitor results are on and could be made. |
| `valid` | boolean | Whether a plan was found |
| `complete` | boolean | Whether it is a whole plan; false for the best partial path |
| `error-message` | string or null | Why there is no plan |

This stream carries no `final` field: every message on it is a result.

```json
{
  "stamp": 1794650533.4,
  "task_sender": "trajectory-generation-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-9be04417-1",
  "trajectory-data": {"random_seed": 1234, "overall_eval_time": 41.7, "trajectories": {"scene_list": []}},
  "valid": true,
  "complete": true,
  "error-message": null
}
```
