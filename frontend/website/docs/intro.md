---
slug: /
sidebar_position: 1
title: Overview
---

# SceneGEMS User Interface Documentation

Complete reference for the browser-based console used to generate maritime ASV assurance scenarios on a cluster, run simulations, and analyze trajectories with COLREGS monitoring.

**SceneGEMS** (Scenario Generation and Execution Framework for Simulation-Based Assurance of Maritime Autonomous Surface Vehicles) is a single-page web application that orchestrates the full lifecycle of a maritime scenario: from domain and functional specification, through the exploration of the design space, automated scene generation and trajectory planning, to simulation and the review of its results.

The console has no backend of its own. It works on the cluster selected in the left pane: it talks to that cluster's control node over the operator API and the workbench gateway, and the cluster's worker nodes run the jobs. Each worker node runs one long-lived subsystem of each kind it offers (design space exploration, scene generation, trajectory generation, monitoring, simulation), and a job is a task of one of them. Key capabilities include:

- Keeping the cluster's domain configuration: COLREGS constants, vessel types and obstacle types, as a form or as YAML
- Authoring and loading functional scenario specifications (`.problem` files), each one a functional equivalence class (FEC)
- Exploring a design space: finding every FEC of a specification within a scope
- Generating scenes from them, one at a time or as a batch, and planning trajectories for the scenes
- Simulating the trajectories as a job on the cluster: unattended, or attended with a real vessel or Mission Planner in the loop
- Following a run on the encounter canvas or the nautical map, with a card per vessel pair, a rule timeline and charts of the distance, DCPA, TCPA and DS index
- Defining campaigns that run these steps on many cases, and following them in Campaign History
- Reviewing the monitor's findings in Results
- Seeing what the cluster's machines run, and what the system can run
- Exporting scenes, trajectories and frames
- Working in dark or light mode
