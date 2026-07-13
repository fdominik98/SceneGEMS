---
slug: /
sidebar_position: 1
title: Overview
---

# SceneGEMS User Interface Documentation

Complete reference for the browser-based console used to generate maritime ASV assurance scenarios, connect to WARA-PS, run simulations, and analyze trajectories with COLREGS monitoring.

**SceneGEMS** (Scenario Generation and Execution Framework for Simulation-Based Assurance of Maritime Autonomous Surface Vehicles) is a single-page web application that orchestrates the full lifecycle of a maritime scenario: from domain and functional specification, through automated scene generation, to live simulation execution and trajectory analysis.

The application communicates with a Python simulation backend over WebSocket. Key capabilities include:

- Editing COLREGS constraints, vessel types, and obstacle types (YAML)
- Authoring and loading functional scenario specifications (`.problem` files)
- Generating initial scenes from specifications (single or batch)
- Visualizing trajectories in Cartesian 3D or nautical GPS map views
- Connecting to WARA-PS via MQTT for live simulation
- Monitoring COLREGS relations with distance, DCPA, TCPA, and danger-sector metrics
- Recording, exporting, and replaying trajectory data
