---
sidebar_position: 15
title: Status indicators & errors
---

# Status indicators & errors

## Step status

The bottom panel of each workbench page shows the state of its step in a chip beside the title:

| Page | States |
|------|--------|
| Scene Generation | Idle, Generating, Generating the batch, Valid scene, No valid scene |
| Trajectory Generation | Idle, Ready to plan, Planning (with the seed step) or Generating, Trajectory ready, Partial trajectory, No usable trajectory, Failed |
| Simulation, on the cluster | Ready to run, Queued, Running, Finishing, Finished, Failed, Stopped |
| Simulation, live session | Not initialized, Initializing, Agents are preparing, Agents are ready, Starting, Running, No simulator connected |

When something outside the panel blocks the run (the cluster, the domain configuration, the MQTT broker), the panel lists it under the header. A disabled run button says in its tooltip what it waits for.

## Connection statuses

The [Connections](./connections) page shows:

- **Server**: the WebSocket link to the workbench gateway of the selected cluster's master; disconnected while no cluster is selected
- **MQTT broker**: the live session's broker connection, and the broker it is connected to
- **Live monitor**: the state of the live COLREGS monitor, once the broker is connected

Status text is colored for quick visual identification. A global error bar at the bottom of the screen shows scene generation and workbench gateway errors; click to dismiss.

## Loading indicators

Spinners appear while the master's FEC catalog, the domain configuration or the capabilities load, and during scene generation.
