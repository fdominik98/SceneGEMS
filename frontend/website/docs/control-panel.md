---
sidebar_position: 9
title: Control panel
---

# Control panel

The bottom panel of the Simulation view runs the page's input trajectories. Playback (play, step, scrub, speed, follow live) is the bar under the canvas, for the preview and the simulation alike. See also [Recording & export](./recording) and [Workbench pages and entries](./workbench-pages).

## Input trajectories

The panel starts with the page's input, which **Take from** sets: **Trajectory page** (the trajectories of the Trajectory Generation page), **Campaign History** (an output of an entry), or **File...**. The input is loaded into the gateway's session for a live session and is what a run on the cluster replays. A run opened from Campaign History fills the input and the setup, so it runs again with one click.

## Where a simulation runs

The setup decides it, and the panel says which:

- **On the cluster**, as one job saved as a workbench entry: every vessel replays its trajectory, or USV Navigation steers the own ship while the others replay, on the kinematic layer, on ArduPilot SITL or Gazebo, or on the custom controller with Gazebo (every vessel on the same control layer). The COLREGS monitor judges every step in the job. **Run on the cluster** creates the entry and **Stop** stops it. **Watch at** sets the pace a kinematic or custom controller run is shown and run at. SITL runs free at the setup's real-time factor, so for a run on ArduPilot **Watch at** is the speed the arriving run plays at in the browser, as the playback bar's speed. The ArduPilot job runs in calm weather; the custom controller's job takes the setup's wind.
- **As a live session** on the control node over the MQTT broker of the [Connections](./connections) page: real vessels, Mission Planner, USV Navigation on a target ship, mixed control layers, ArduPilot with wind or waves, and the custom controller with waves. **Initialize** builds the session, **Start** starts it once the agents are ready, **Reset** ends it.

When something is missing (no input trajectories, no machine on the cluster that runs simulations, no broker connection), the panel lists it instead of enabling the action.

## Setup

| Control | Description |
|---------|-------------|
| Simulator | The simulation layer every simulated vessel shares: Kinematic, ArduPilot Sim or Gazebo |
| Pace | The real-time factor of a live session or of a run on ArduPilot; a kinematic or custom controller run on the cluster takes **Watch at** instead |
| Seed | On the cluster: the base seed of the entry; empty for a random one |
| Vessel table | Per vessel: **Kind** (simulated or real vessel), **ASV system** and **control layer**. Choices the server rules out are disabled with the reason. A real vessel is its own control layer and physics, reached through its ArduAgent; it is steered by Replay or Mission Planner, or left to its own software (**On board**). |
| Wind and waves | Wind and waves (simulated vessels only) |
| Agent connections | MQTT agent names, topics and MAVLink ports of a live session |
| Gazebo models | Gazebo only: load, export or clear a vessel's SDF model, or ask the server for the models it would make; the server makes one otherwise |

Real vessels and Mission Planner never run in a campaign: they are workbench only.

## Result

The Result row says how many frames the run has and over which time, and which entry the page shows. For a live session it also says whether the session is recording, saved (with **Open the recorded run**), failed, or not recorded on this gateway, and which addresses Mission Planner connects to.
