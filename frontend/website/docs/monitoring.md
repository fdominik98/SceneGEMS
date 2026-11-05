---
sidebar_position: 10
title: Monitoring panel
---

# Monitoring panel

The right pane of the Trajectory Generation and Simulation pages inspects the frames of a run. Its tabs switch between:

- **Live data**: The vessel pairs and the data of the current frame
- **Charts**: Time-series metric charts (see [Metrics & analysis](./metrics))

**Hide monitoring panel** in the toolbar hides the pane. Restore it with **Show monitoring panel** in the canvas toolbar.

## Preview and Simulation

The panel shows one stream at a time. The bar under the tabs names it, and offers a switch between **Preview** and **Simulation** once a simulation has frames; the panel moves to the simulation when a run starts sending them. The Trajectory Generation page has the preview only. The button at the end of the bar downloads the shown stream's frames as JSON.

Which layers the canvas draws is set in the canvas's own [Layers menu](./scene-canvas#layers), not here.

## Vessel pairs

A card per vessel pair at the current time, with an encounter:

- The two vessels with their roles (**GW** give-way, **SO** stand-on) and the encounter type
- The range, the bearing and the CPA
- Flags such as a collision course or a low TCPA
- A chip per rule with its result, and when a failed rule first failed
- **Details** with more on the pair and its rules

Vessel pairs that are in no encounter are listed in a short row each under **No encounter**. Clicking a card selects the pair: the canvas draws the line between the two vessels and the rule timeline highlights it.

## Frame data

The monitor's data of the current frame, at the time of the playhead or of the newest live frame, in sections that remember whether they are open:

| Section | What it holds |
|---------|---------------|
| Vessels & actors | Per actor: its static values and limits, and its state (position, heading, speed) |
| Encounter summary | The vessel pairs at a glance |
| Situation contexts | The COLREGS situation of each pair, as the monitor sees it |
| COLREGS monitor state | The monitor's own state |
| COLREGS rules | Each rule's result per pair, with **Fail**, **Pass** and not applicable yet |
| Maneuvers | Each vessel's maneuver: the turn, the distance made and whether it counts as readily apparent |
| Metrics | The values the charts plot |
| Trajectory samples | The points the frame carries, when it has any |
| Additional frame fields | Anything else the monitor sent |

On Scene Generation, the **Monitor preview** tab of the right pane shows the same Frame data for the shown scene.
