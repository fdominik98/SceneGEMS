---
sidebar_position: 5
title: Trajectory Generation
---

# Trajectory Generation

The Trajectory Generation page plans the vessels' routes from a scene, as a job on the active cluster. It has the [scene canvas](./scene-canvas) with the playback bar and the rule timeline under it, the bottom panel described here, and the [monitoring panel](./monitoring) on the right, which shows the planned preview. Every run is saved as a workbench entry (see [Workbench pages and entries](./workbench-pages)).

**Generate trajectories** runs the job and **Stop** stops it. It needs an input scene and a machine that offers trajectory generation; without such a machine the panel says why and the button stays off.

## Input

A scene, from one of:

- **Scene page**: the valid scene the Scene Generation page shows. **Next: Trajectory Generation** on that page does the same and opens this one.
- **Campaign History**: an output of an entry that ran scene generation.
- **File...**: a scene file (JSON).

The canvas shows the input scene until there are trajectories to show.

## Setup

| Control | Description |
|---------|-------------|
| Generator | **Monitor-guided planner** follows a maneuvering corridor for every give-way vessel and repairs each step the COLREGS monitor fails with a short tree search over sampled heading changes; it stops on Stop, the timeout or the seed step cap. **Straight** sends every vessel straight on from its initial state: nothing is searched, so it is ready at once and always complete. |
| Timespan | Straight only: how long the vessels go on, in seconds |
| Seed | The base seed of the entry; empty for a random one (see [Every run is an entry](./workbench-pages#every-run-is-an-entry)) |
| Search settings | Time step, timeout, max seed steps, rejoin tolerance (how close a repaired stretch must come to the seed path), leaves expanded per repair round and how often a preview is sent. **Monitor results in previews** sends the monitor's output with each preview, so the side panel fills and the domains are drawn while planning; off keeps previews small on long runs. **Reset to the defaults** restores them. For Straight, this link holds the time step only. |

## Result

While the search runs, the canvas shows the best path so far and the status counts the seed steps. The result is one of:

- **Trajectory ready**: a complete plan.
- **Incomplete trajectory**: the planner found no complete plan, so this is the best path it found: it ends early or still fails a COLREGS rule. It can still be simulated and exported.
- **No usable trajectory**: the planner found no compliant step from this scene.

The button with the download icon exports the trajectory as JSON. **Next: Simulation** makes it the input of the Simulation page and opens it; it needs the gateway connection.
