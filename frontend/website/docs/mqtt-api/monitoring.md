---
title: Monitoring MQTT API
sidebar_label: Monitoring
---

# Monitoring subsystem

Judges a series of scenes against COLREGS as the scenes arrive. A request is one task: one series of one scenario. The request opens the series, the scenes follow as `scenes` signals in time order, and a `close` signal ends it. The monitor keeps its rule outcomes from the first scene to the last, so a rule is judged over the whole series.

| Property | Value |
|----------|-------|
| Name | `monitoring-subsystem`, on a worker node `monitoring-subsystem-<n>` |
| Base topic | `<root>/service/virtual/real/<name>` |
| Task | `monitor-scenario` |
| Signals | `cancel`, `scenes`, `close` |
| Streams | `monitored-scene`, `monitor_result` |

The heartbeat, the declarations, the command envelope and the task states are in [Subsystem channels](./subsystem-channels).

Two series of one scenario never run at once: the later one stays `queued` until the earlier is over. Series of different scenarios run side by side, as many as the pool has places.

## Channels

| Operation | Topic | Message |
|-----------|-------|---------|
| SUB | `<base>/exec/command` | [monitor-scenario](#monitor-scenario) |
| SUB | `<base>/exec/command` | [scenes signal](#scenes-signal) |
| SUB | `<base>/exec/command` | [close signal](#close-signal) |
| PUB | `<base>/sensor/monitored-scene` | [Monitored scene](#monitored-scene) |
| PUB | `<base>/exec/feedback` | [Stop advised](#stop-advised) |
| PUB | `<base>/sensor/monitor_result` | [Monitor result](#monitor-result) |

## Quick start

1. Send `monitor-scenario` with the scenario's id and its time step, and wait for the response `running`.
2. Send the scenes in batches, each as a `scenes` signal with the batch's `index`, starting at 0. The requesters of SceneGEMS put 100 scenes in a batch.
3. Read one `monitored-scene` message per batch: how far the series is, and whether every rule has its final outcome.
4. Send `close` with the number of batches, and read the verdict on `monitor_result`.

## monitor-scenario

**SUB** `<base>/exec/command`

The fields of `task.params`, next to `request-id` and `seed`. The monitor draws nothing at random; the seed is carried for the record.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario-id` | string | yes | The scenario of the series: the `scenarioId` of its frames, and what orders two series of one scenario. Not empty. |
| `time-step` | integer | yes | Seconds between two scenes of the series, at least 1 |
| `colregs-constraints-content` | string or null | yes | The COLREGS constants, as YAML text. The key must be there; null means the general maritime defaults. |
| `include-frames` | boolean | no | Whether every `monitored-scene` message carries the monitored frames of its batch. False when left out. |

```json
{
  "stamp": 1794650475.108,
  "task_sender": "pool_client",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "command": "start-task",
  "execution-unit": "monitoring-subsystem-2",
  "task": {
    "name": "monitor-scenario",
    "params": {
      "scenario-id": "crossing-017",
      "time-step": 1,
      "colregs-constraints-content": null,
      "include-frames": false,
      "request-id": "job-2d8e11f3-1",
      "seed": 0
    }
  }
}
```

## scenes signal

**SUB** `<base>/exec/command`

The next scenes of the series. The fields of `signal.data`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `index` | integer | yes | The batch's number in the series, from 0 |
| `scenes` | object[] | yes | The scenes of the batch in time order, each a concrete scene |
| `first-timestamp` | integer | no | The timestamp of the batch's first scene: the scenes sent so far times the time step. Checked against the series when given. |
| `frames` | boolean | no | Whether this batch's `monitored-scene` message carries its frames. Wins over the request's `include-frames`; a run that is judged while it runs asks only for the batches somebody watches. |

```json
{
  "stamp": 1794650476.5,
  "task_sender": "pool_client",
  "task-uuid": "9c8b7a6f-5e4d-4c3b-9a19-8f7e6d5c4b3a",
  "command": "signal-task",
  "execution-unit": "monitoring-subsystem-2",
  "signal": {
    "name": "scenes",
    "request-id": "job-2d8e11f3-1",
    "data": {"index": 0, "first-timestamp": 0, "scenes": [], "frames": false}
  }
}
```

| Case | What happens |
|------|--------------|
| A batch arrives a second time | It is taken once |
| A batch arrives before the one it follows | The task fails: the monitor only takes the scene after the last |
| `first-timestamp` is not where the series is | The task fails |
| No signal for 300 seconds | The task fails, so a requester that is gone holds no place in the pool |

## close signal

**SUB** `<base>/exec/command`

The series is over. The fields of `signal.data`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `batches` | integer | no | How many batches the series had. A series closed before all of them arrived fails. |

## Monitored scene

**PUB** `<base>/sensor/monitored-scene`

One message per judged batch.

| Field | Type | Description |
|-------|------|-------------|
| `scenario-id` | string | The scenario of the series |
| `index` | integer | The batch's number |
| `monitored-scenes` | integer | How many scenes of the series are judged so far |
| `every-rule-decided` | boolean | Whether every rule of every relation has its final outcome. Only a failure is final. |
| `monitored-frames` | object[] | The monitored frames of the batch when they were asked for, else empty. A monitored frame is a frame with `situationContexts`, `colregsStates`, `ruleResults` and `maneuverStates` filled in. |
| `final` | boolean | Always false |

```json
{
  "stamp": 1794650476.9,
  "task_sender": "monitoring-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-2d8e11f3-1",
  "scenario-id": "crossing-017",
  "index": 0,
  "monitored-scenes": 100,
  "every-rule-decided": false,
  "monitored-frames": [],
  "final": false
}
```

## Stop advised

**PUB** `<base>/exec/feedback`

Published once, when every rule has its final outcome: a requester that produces the scenes may stop. The series still has to be closed.

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | `every rule is decided` |
| `progress` | null | Not used |
| `detail.stop-advised` | boolean | Always true |
| `detail.decided-at` | integer | The timestamp of the scene that decided the last rule |

## Monitor result

**PUB** `<base>/sensor/monitor_result`

The verdict of the closed series: one message, after the `close` signal.

| Field | Type | Description |
|-------|------|-------------|
| `scenario-id` | string | The scenario of the series |
| `scenes` | integer | How many scenes the series had |
| `monitored-scenes` | integer | How many of them were judged |
| `time-step` | integer | Seconds between two scenes |
| `batches` | integer | How many batches the series had |
| `summary.passed` | boolean | Whether no rule failed |
| `summary.rules` | object | Per relation and rule, the first timestamp it `passed` and the first it `failed` |
| `summary.failed_rules` | object[] | The failed rules by first failure time: `relation`, `rule`, `first_failed_at` |
| `summary.encounters` | object | Per relation, the situation types of the pair in order of first appearance |
| `summary.encounter_roles` | object | Per relation and situation type, the vessel names by role (`give_way`, `stand_on`) |
| `final` | boolean | Always true |

```json
{
  "stamp": 1794650490.2,
  "task_sender": "monitoring-subsystem-2",
  "task-uuid": "1a2b3c4d-5e6f-4789-9abc-def012345678",
  "request-id": "job-2d8e11f3-1",
  "scenario-id": "crossing-017",
  "scenes": 600,
  "monitored-scenes": 600,
  "time-step": 1,
  "batches": 6,
  "summary": {"passed": true, "rules": {}, "failed_rules": [], "encounters": {}, "encounter_roles": {}},
  "final": true
}
```

## Series of a run that is judged while it runs

A simulation that is judged while it runs has a series of its own in the monitoring subsystem of the same worker node. The run's runner container is the requester. The request id of that series is the run's request id followed by `-live`. When the run's task ends, the simulation subsystem sends a `cancel` for that request id, so a series whose runner was killed holds no place in the pool; for a series that is already closed the cancel changes nothing.
