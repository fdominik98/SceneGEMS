---
sidebar_position: 15
title: Status indicators & errors
---

# Status indicators & errors

## Step status

The bottom panel of each workbench page shows the state of its step in a chip beside the title:

| Page | States |
|------|--------|
| Design Space Exploration | No input yet, Input incomplete, Ready to explore, Exploring, N FECs found, No FEC found |
| Scene Generation | No input yet, Ready to generate, Generating, Generating the batch, Valid scene, No valid scene |
| Trajectory Generation | No input yet, Ready to plan, Planning (with the seed step) or Generating, Trajectory ready, Incomplete trajectory, No usable trajectory, Failed |
| Simulation | No input yet, Ready to run, Queued, Running, Finishing, Finished, Failed, Stopped |
| Simulation, attended run | As above, and **Ready to start** once the job has brought the vessels up and waits for **Start**. Before that the Result row lists what each vessel still waits for: its agent on the broker, a position, to be at its start point, to be armable. |

When something outside the panel blocks the run (the cluster, the domain configuration), the panel lists it under the header. A disabled run button says in its tooltip what it waits for.

## Connection status

The console has one connection of its own: the WebSocket link to the workbench gateway of the selected cluster's control node, which reads scenario files and lists the stack options. It is disconnected while no cluster is selected. The console connects to no MQTT broker: the [Connections](./connections) page only holds the broker setting of a run with a real vessel.

Status text is colored for quick visual identification. A global error bar at the bottom of the screen shows scene generation and workbench gateway errors; click to dismiss.

## Loading indicators

Spinners appear while the control node's FEC catalog, the domain configuration or the capabilities load, and during scene generation and while the design space exploration waits for its job.
