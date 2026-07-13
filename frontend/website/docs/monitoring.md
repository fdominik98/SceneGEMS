---
sidebar_position: 10
title: Monitoring sidebar
---

# Monitoring sidebar

The right pane in Simulation view provides deep inspection of trajectory data. Use the **View** dropdown to switch between:

- **Runtime data**: Layer controls and per-actor information
- **Overall analysis**: Time-series metric charts (see [Metrics & analysis](./metrics))

## Preview and Simulation columns

Both views use a split layout with Preview and Simulation columns. Each column can be hidden independently; hidden columns show a reveal strip on the edge. When both are visible, a vertical resizer adjusts the split ratio.

Each column header provides:

- **Export** (runtime data only): Download trajectory frames as JSON
- **Hide**: Collapse the column

## Actor visibility panel

Collapsible section per stream with a master toggle to show/hide the entire stream on the map, plus individual layer checkboxes (dot, velocity, safety radius, trajectory, safety domains).

## Basic actor info panel

Lists actors in the current frame with kinematic state (position, heading, speed), COLREGS role, and rule status. Updates with the animation playhead or live simulation frames.

## Scenario diff

When both preview and simulation frames are available, a comparison table shows position deltas and rule-status mismatches between streams at the current playhead.

Use **Hide panel ▶** in the sidebar header to collapse the entire monitoring sidebar. Restore it with the floating Monitor button on the right edge of the canvas.
