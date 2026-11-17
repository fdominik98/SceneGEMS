---
title: MQTT API overview
sidebar_label: Overview
---

# SceneGEMS MQTT API

Version: 1.0.0

## Overview

The subsystems of a SceneGEMS cluster and the agents of its vessels talk over MQTT. Their topics and messages follow the agent API of WARA-PS, so a subsystem looks like a WARA-PS service agent and a vessel like a WARA-PS unit agent. The WARA-PS specifications this API builds on:

- [WARA-PS Declarations MQTT API](https://waraps.org/docs/asyncapi/waraps-api-declarations/waraps-api-declarations): heartbeat, sensor info and direct execution info
- [WARA-PS Sensors MQTT API](https://waraps.org/docs/asyncapi/waraps-api-sensors/waraps-api-sensors): the telemetry channels of a unit
- [WARA-PS Tasks MQTT API](https://waraps.org/docs/asyncapi/waraps-api-tasks/waraps-api-tasks): commands, signals, responses and feedback
- [WARA-PS Map Objects MQTT API](https://waraps.org/docs/asyncapi/waraps-api-map-objects/waraps-api-map-objects): what the WARA-PS map draws

The index of all of them is the [WARA-PS documentation](https://waraps.org/docs/intro).

The browser never talks to a broker: the console uses the control node's operator API and workbench gateway. This reference is for whoever puts an agent on the broker, reads the traffic of a cluster, or adds a subsystem.

## Quick start

A request to a subsystem, in plain terms:

1. The subsystem publishes its heartbeat once a second, so a requester knows it is there.
2. The requester publishes a `start-task` command on the subsystem's `exec/command`, with the inputs, a request id and a seed.
3. The subsystem answers on `exec/response` with every state the task goes through: `received`, `queued`, `running`, and at the end `finished`, `failed` or `aborted`.
4. While the task runs, the subsystem publishes progress on `exec/feedback` and previews and results on `sensor/<stream>`.
5. The requester may send a `signal-task` command at any time: `cancel`, or one of the subsystem's own signals.

A vessel's agent works the same way with the tasks of the WARA-PS Tasks API (`move-to`, `move-path`) and publishes its telemetry on the channels of the WARA-PS Sensors API.

## Agents

| Agent | WARA-PS agent type | Base topic | Reference |
|-------|--------------------|------------|-----------|
| Design space exploration subsystem | service, level 2 (task agent) | `<root>/service/virtual/real/design-space-exploration-subsystem-<n>` | [Design space exploration](./design-space-exploration) |
| Scene generation subsystem | service, level 2 | `<root>/service/virtual/real/scene-generation-subsystem-<n>` | [Scene generation](./scene-generation) |
| Trajectory generation subsystem | service, level 2 | `<root>/service/virtual/real/trajectory-generation-subsystem-<n>` | [Trajectory generation](./trajectory-generation) |
| Monitoring subsystem | service, level 2 | `<root>/service/virtual/real/monitoring-subsystem-<n>` | [Monitoring](./monitoring) |
| Simulation subsystem | service, level 2 | `<root>/service/virtual/real/simulation-subsystem-<n>` | [Simulation](./simulation) |
| Vessel agent (ArduAgent) | unit, level 2 | `<root>/unit/surface/simulation/<name>` or `<root>/unit/surface/real/<name>` | [Vessels](./vessels) |

The channels every subsystem has, and the task states, are in [Subsystem channels](./subsystem-channels). The page of a subsystem lists only what is its own: its task, its signals, its streams and their messages.

## Servers

| Name | Protocol | Host | Topic root | Description |
|------|----------|------|------------|-------------|
| cluster broker | mqtt 3.1.1 | `cluster-broker:1883` | `scenegems` | The control node's own broker (NanoMQ), the service `cluster-broker` of the cluster's namespace. Plain MQTT without accounts, reachable from the cluster's pods only. Takes packets up to 256 MB. |
| WARA-PS | mqtt 3.1.1 over TLS | `broker.waraps.org:8883` | `waraps` | The public WARA-PS broker, for runs with a real vessel or external agents. Needs an account. |
| other broker | mqtt 3.1.1, plain or TLS | as set on the [Connections](../connections) page | `waraps` | Any external broker a run with a real vessel is given. |

The subsystems of a worker node are always on the cluster broker. Vessel agents are on the cluster broker unless a run names an external one (see [Connections](../connections)); then every vessel of that run is on the external broker.

## Topic layout

Every agent topic has the layout of the WARA-PS agent API under the first level of the broker:

```text
<root>/<agent type>/<domain>/<real or simulation>/<name>/<channel>
```

| Level | Values |
|-------|--------|
| `<root>` | `scenegems` on a control node's own broker, `waraps` on a WARA-PS broker and on any other external one |
| `<agent type>` | `service` for a subsystem, `unit` for a vessel |
| `<domain>` | `virtual` for a subsystem, `surface` for a vessel |
| `<real or simulation>` | `real` for a subsystem and for a real vessel, `simulation` for a simulated vessel |
| `<name>` | The agent's name, unique on its broker |
| `<channel>` | `heartbeat`, `exec/command`, `exec/response`, `exec/feedback`, `sensor/<name>` and the other channels of the agent |

A topic names the agent that publishes, never the control node or the worker node it runs on. On a control node's own broker the root is `scenegems` because the topics belong to that cluster; nothing in a topic tells two clusters apart, since each has a broker of its own.

## Names

| Agent | Name | Example |
|-------|------|---------|
| Subsystem of a worker node | The subsystem's name and the number the control node gave the worker node | `scene-generation-subsystem-2` |
| Subsystem on its own | The subsystem's name alone, or the name in `MQTT_SERVICE_NAME` | `scene-generation-subsystem` |
| Simulated vessel of a job | The vessel's name (`os`, `ts1`, `ts2`) and the first 8 characters of the job id | `ts1-4f6c0a1e` |
| Real vessel | The last level of the topic the operator gives for it | `MiniUSV3` |

A name is one topic level: it has no `/`, `+` or `#`. A subsystem ignores every command whose `execution-unit` is not its own name, so two instances on one broker never take each other's requests.

## Message conventions

- Payloads are JSON in UTF-8, except the scalar sensor channels of a vessel (speed, heading, clock, mode), which carry the bare value.
- Field names of the envelope are in kebab case (`task-uuid`, `request-id`, `fail-reason`), as in the WARA-PS API. `task_sender` is the one exception.
- `stamp` is the sender's wall clock in seconds since the Unix epoch.
- A subsystem publishes and takes everything with QoS 1. A vessel agent publishes with QoS 0 and takes commands with QoS 1.
- No message is retained.
- A frame is the console's simulation frame: `scenarioId`, `timestamp`, `timeStep`, `actors`, `statesByActorId`, and, when it was monitored, `situationContexts`, `colregsStates`, `ruleResults` and `maneuverStates`. Positions are metres in the scenario's local frame, whose origin is the centre of the reference area (see [Connections](../connections)).

## Who is on the broker

| Client | What it does |
|--------|--------------|
| Subsystem | Takes requests and signals, publishes states, progress, streams and its declarations |
| Worker node daemon | The requester of a cluster job: one client per job, which sends the request and the signals and hears the task |
| Control node | Listens to the preview streams of the pools an operator watches on the [Cluster](../cluster) page |
| Runner container of a judged run | A requester of the worker node's monitoring subsystem: it sends the scenes of the run as a series |
| Vessel agent | Publishes the vessel's telemetry and takes its tasks |

## Differences from the WARA-PS agent API

The layout, the channels and the message types are those of WARA-PS. A subsystem differs from a WARA-PS task agent where a pool of tasks needs it:

| Topic or field | WARA-PS agent API | SceneGEMS subsystem |
|----------------|-------------------|---------------------|
| Sensor info topic | `<base>/sensor_info` | `<base>/sensor/sensor_info` |
| Direct execution info topic | `<base>/direct_execution_info` | `<base>/direct_execution` |
| Tasks at once | One; a command during a running task is rejected | As many as the pool has places; the others wait as `queued` |
| Sender of a command | `sender`, with a `com-uuid` | `task_sender`, with a `stamp` and no `com-uuid` |
| Signal | A string: `$abort`, `$pause`, `$continue`, `$enough` | An object with `name`, `request-id` and `data` |
| What a signal addresses | The task, by `task-uuid` | The tasks of a request, by `request-id` |
| Response values | `running`, `finished`, `failed` | `received`, `queued`, `running`, `finished`, `failed`, `aborted` |
| Response fields | `agent-uuid`, `com-uuid`, `response`, `task-uuid` | `stamp`, `task_sender`, `task-uuid`, `request-id`, `response`, `fail-reason`, `seed` |
| Direct execution info | `tasks-available`, `tasks-executing` | Also `tasks-queued` and `pool-size` |
| Quality of service of the declarations | 0 | 1 |

A vessel agent follows the WARA-PS agent API; the channels it adds are listed on the [Vessels](./vessels) page.
