---
sidebar_position: 9
title: Control panel
---

# Control panel

The bottom panel of the Simulation view runs the page's input trajectories. Playback (play, step, scrub, speed, follow live) is the bar under the canvas, for the preview and the simulation alike. See also [Recording & export](./recording) and [Workbench pages and entries](./workbench-pages).

## Input trajectories

The panel starts with the page's input, which **Take from** sets: **Trajectory page** (the trajectories of the Trajectory Generation page), **Campaign History** (an output of an entry), or **File...**. The input is what a run replays. A run opened from Campaign History fills the input and the setup, so it runs again with one click.

## Where a simulation runs

Every run is one job on a worker node of the selected cluster, saved as a workbench entry. The worker node's simulation subsystem brings the vessels of the run up, runs them and removes them again; nothing runs on the control node or in the browser. **Run on the cluster** creates the entry and **Stop** stops it. The setup decides which kind of run it is, and the panel says which:

- **Unattended**: every vessel replays its trajectory, or USV Navigation steers the own ship while the others replay, on the kinematic layer, on ArduPilot SITL or Gazebo, or on the custom controller with Gazebo (every vessel on the same control layer). The run starts on its own. **Watch at** sets the pace a kinematic or custom controller run is shown and run at. SITL runs free at the setup's real-time factor, so for a run on ArduPilot **Watch at** is the speed the arriving run plays at in the browser, as the playback bar's speed. The ArduPilot job runs in calm weather; the custom controller's job takes the setup's wind.
- **Attended**: a setup no unattended run takes. That is a real vessel, Mission Planner, USV Navigation on a vessel other than the own ship, vessels on different control layers, wind or waves on the kinematic layer or on ArduPilot, and waves with the custom controller. The job brings the vessels up and then waits for you: the chip says **Ready to start**, and **Start** starts the run. Until then **Start** is disabled and the Result row says what each vessel still waits for. The panel says why the setup runs attended.

The COLREGS monitor judges every run as it goes on. The worker node's monitoring subsystem does that, so a run needs a worker node that has every layer of its vessels' stacks and also runs monitoring.

When something is missing (no input trajectories, no machine on the cluster that can run the simulation), the panel lists it instead of enabling the action.

## Setup

| Control | Description |
|---------|-------------|
| Simulator | The simulation layer every simulated vessel shares: Kinematic, ArduPilot Sim or Gazebo |
| Pace | The real-time factor of an attended run or of a run on ArduPilot; a kinematic or custom controller run takes **Watch at** instead |
| Seed | The base seed of the entry; empty for a random one |
| Vessel table | Per vessel: **Kind** (simulated or real vessel), **ASV system** and **control layer**. Choices the server rules out are disabled with the reason. A real vessel is its own control layer and physics, reached through its ArduAgent; it is steered by Replay or Mission Planner, or left to its own software (**On board**). |
| Wind and waves | Wind and waves (simulated vessels only) |
| Agent connections | For a real vessel: the topic its agent on board publishes on. A simulated vessel gets its topic from the job that runs it (the vessel's name and the job's id), so there is nothing to set. The vessels' names are fixed: `os` for the own ship, `ts1`, `ts2` and so on for the others. |
| Gazebo models | Gazebo only: load, export or clear a vessel's SDF model, or ask the server for the models it would make; the server makes one otherwise |

Real vessels and Mission Planner never run in a campaign: they are workbench only.

## A run with a real vessel

A real vessel takes part through its ArduAgent on an MQTT broker. The [Connections](./connections) page says which broker: the control node's own, which the vessel reaches over the cluster's VPN, or an external one. The worker node that runs the job must reach that broker too. The simulated vessels of such a run are steered through agents as well, so every vessel is commanded the same way.

The run is ready to start when every vessel has its agent on the broker, reports a position, is at its start point and, where the run commands it, can be armed. The Result row lists what each vessel still waits for, for example "vessel 1 waits for a position, to be at its start point".

Stopping the job ends the run on the cluster. It does not abort a mission a real vessel is already on: stop the vessel with its own controls.

## Result

The Result row says how many frames the run has and over which time, and which entry the page shows. For an attended run it also lists what the vessels still wait for and, for a vessel steered from Mission Planner, the address to connect it to (`vessel 1: TCP <host>:<port>`).
