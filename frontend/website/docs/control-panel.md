---
sidebar_position: 9
title: Control panel
---

# Control panel

The bottom toolbar in Simulation view hosts a tabbed control panel with three modes.

## Animation tab

Controls playback of buffered preview/animation trajectory frames.

| Control | Description |
|---------|-------------|
| Step Back / Step Forward | Move the playhead by N frames, where N equals the rounded playback speed |
| Play / Pause | Start or stop automatic playback |
| Reset | Return playhead to the start and pause |
| Animation Time slider | Scrub to any timestamp in the buffered preview stream |
| Speed slider | Playback rate from 0.5× to 240× |

See also [Recording & replay](./recording).

## Simulation tab

Manages live WARA-PS simulation execution. A status bar shows simulation state and buffered frame count.

| Control | Description |
|---------|-------------|
| Initialize Simulation | Sends vessel connection configuration to the backend. Requires initialized scenario and connected WARA-PS. |
| Start | Starts simulation agents when status is "ready to start" |
| Reset Simulation | Resets the running simulation |
| Live | Jumps to the latest simulation frame and enables live follow mode |
| Generate Vessel Physics Models | Requests SDF/world model generation for vessels in the loaded scenario |

### Vessel initialization table

Below the action buttons, an expandable table lists each vessel in the scenario with per-vessel settings:

- Control mode (autonomous, manual, etc.)
- Simulator type (global default or per-vessel override)
- Connection topic segments for MQTT routing
- Physics model files (SDF/XML): load, export, or clear custom models
- **Simulation speed** (1–50): integer physics time multiplier sent with `initialize_simulation` and `generate_simulation_models` as `simulationSpeed` (1 = real-time)
- Wave and environmental parameters where applicable

Simulation status values include: running, starting, agents are preparing, initializing, ready to start, offline, and not initialized.

## Monitor tab

Configures the COLREGS trajectory monitor published over MQTT.

| Field | Description |
|-------|-------------|
| Scope | Internal or external monitor deployment |
| Name | Monitor instance name (updates the default topic) |
| Topic | MQTT topic for monitor output |
| Initialize Monitor | Starts the monitor with current COLREGS YAML. Requires WARA-PS connected and non-empty COLREGS config. |
| Shut Down | Stops the active monitor |
