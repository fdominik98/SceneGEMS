---
sidebar_position: 4
title: Workbench pages and entries
---

# Workbench pages and entries

The Design Space Exploration, Scene Generation, Trajectory Generation and Simulation pages are independent. Each holds its own **input** and the **latest loaded entry**, so the scene page and the trajectory page may show outputs of different campaigns. A new run uses the page's input.

## Every run is an entry

Every design space exploration, scene generation, trajectory generation and simulation on the cluster is saved as a one-step **workbench entry** of [Campaign History](./campaign-history): a batch scene generation is one entry with a case per FEC. The entry records the input it used, so Campaign History shows what it was made from. Each entry gets a fresh random base seed, so two runs of the same input give different results. To repeat a run, type a seed into **Seed** in the page's Setup row (or click **Keep** for the seed the last run used): every entry then takes it, in every step. Empty the field to go back to random seeds. A page says which entry it shows, such as "Shows case 12 of entry 4f2c...".

A run on ArduPilot SITL or Gazebo is an entry too: its run is the ArduPilot stack with the setup's real-time factor as SITL's pace and the Connections page's reference area. A run on the custom controller with Gazebo is one with the setup's wind. Loading such a run fills the setup again with the simulator, the control layer, replay or USV Navigation on the own ship, and the pace or the wind.

## Setting a page's input

The trajectory page takes a scene, the simulation page takes trajectories. Each sets its input in one click from one of three places:

| Source | What it takes |
|--------|---------------|
| **Scene page** or **Trajectory page** | The scene the Scene Generation page shows, or the trajectories the Trajectory Generation page shows. **Next: Trajectory Generation** and **Next: Simulation** do the same and open the page. |
| **Campaign History** | An output of an entry that ran the step: pick the entry, then one of its outputs. Dropped cases have no output and cannot be picked. |
| **File...** | A scenario file. It is uploaded to the master when a run starts. |

The input line says what the input is and where it came from. An input from a file is kept only while the app runs: after a reload choose it again. An input from Campaign History or from an entry of the previous page stays.

The scene page's input is its FEC: one of the master's catalog, a file, what you write in the editor, or one found on the [Design Space Exploration](./design-space-exploration.md) page. The exploration page has no input from another page: its input is the specification and the scope it keeps itself.

On the Simulation page the input and the run share the canvas and the live session, so a new input replaces the shown run.

## Loading outputs from Campaign History

**Open in workbench** in Campaign History shows an output on the page of its step:

- An exploration loads with its FECs, and its specification, scope and limits become the page's input.
- A scene loads with the scene monitor's judgment of it.
- Trajectories load with the trajectory monitor's frames, as planned.
- A simulated run loads as a replay of its frames with the monitor, and fills the setup (simulator, vessel stacks, wind and waves) and the input trajectories, so **Run on the cluster** runs it again.

**Watch live** on a running entry opens its page and follows the job: the exploration's progress, scene previews, trajectory previews, or the simulation at the **Watch at** speed. When the job ends, the page shows the entry's output.

The contents are fetched from the master: after a reload each page loads its entry again. When the entry was deleted, the page shows nothing of it any more and says so; its input stays.

## Live sessions

A live session (real vessels, Mission Planner, USV Navigation on a target ship, mixed control layers, ArduPilot with wind or waves, the custom controller with waves) runs on the master over the MQTT broker and is recorded as an entry too. The control panel shows whether it is being recorded, when it is saved (with **Open the recorded run**, which replays it on the Simulation page), when the recording failed, or that the gateway records nothing (a gateway started without a master).
