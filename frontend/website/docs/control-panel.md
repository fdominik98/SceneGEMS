---
sidebar_position: 9
title: Control panel
---

# Control panel

The bottom panel of the Simulation view runs the page's input trajectories. Playback (play, step, scrub, speed, follow live) is the bar under the canvas, for the preview and the simulation alike. See also [Recording & replay](./recording) and [Workbench pages and entries](./workbench-pages).

## Input trajectories

The panel starts with the page's input: the trajectories of the Trajectory Generation page, an output of Campaign History, or a file. The input is loaded into the gateway's session for a live session and is what a run on the cluster replays. A run opened from Campaign History fills the input and the setup, so it runs again with one click.

## Where a simulation runs

The setup decides it, and the panel says which:

- **On the cluster**, as one job saved as a workbench entry: every vessel replays its trajectory, or USV Navigation steers the own ship while the others replay, on the kinematic layer, on ArduPilot SITL or Gazebo, or on the custom controller with Gazebo (every vessel on the same control layer). The COLREGS monitor judges every step in the job. **Run on the cluster** creates the entry and **Stop** stops it. **Watch at** sets the pace a kinematic or custom controller run is shown and run at. SITL runs free at the setup's real-time factor, so for a run on ArduPilot **Watch at** is the speed the arriving run plays at in the browser, as the playback bar's speed. The ArduPilot job runs in calm weather; the custom controller's job takes the setup's wind.
- **As a live session** on the master over the MQTT broker of the [Connections](./connections) page: real vessels, Mission Planner, USV Navigation on a target ship, mixed control layers, ArduPilot with wind or waves, and the custom controller with waves. **Initialize** builds the session, **Start** starts it once the agents are ready, **Reset** ends it.

When something is missing (no input trajectories, no machine on the cluster that runs simulations, no broker connection), the panel lists it instead of enabling the action.

A live session is recorded as a workbench entry; the panel shows whether it is recording, saved (with **Open the recorded run**), failed, or not recorded on this gateway.

## Setup

| Control | Description |
|---------|-------------|
| Simulator | The simulation layer every simulated vessel shares: Kinematic, ArduPilot Sim or Gazebo |
| Vessel table | Per vessel: **Kind** (simulated or real vessel), **ASV software** and **control layer**. Choices the server rules out are disabled with the reason. A real vessel is its own control layer and physics, reached through its ArduAgent; it is steered by Replay or Mission Planner, or left to its own software (**On board**). |
| Wind, waves and pace | Wind and waves (simulated vessels only) and the real-time factor of a live session |
| Agent names, topics and ports | MQTT agent names, topics and MAVLink ports of a live session |
| Gazebo vessel models | Gazebo only: load, export or clear a vessel's SDF model; the server makes one otherwise |

Real vessels and Mission Planner never run in a campaign: they are workbench only.

## More

Follow the newest frame, generate Gazebo vessel models, and record or replay a run.
