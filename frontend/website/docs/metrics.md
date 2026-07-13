---
sidebar_position: 11
title: Metrics & analysis
---

# Metrics & analysis

In **Overall analysis** view, each stream column shows COLREGS metric time-series charts for the selected vessel relation pair.

## Relation selector

Dropdown of available actor-pair relations detected in the trajectory. Changing the selection updates all charts simultaneously for both preview and simulation columns.

## Charts

| Chart | Description |
|-------|-------------|
| Distance | Range between vessels over time |
| DCPA | Distance at closest point of approach |
| TCPA | Time to closest point of approach |
| Danger sector (DS) | COLREGS danger-sector index |

Charts respect the animation playhead: only frames at or before the current cursor timestamp are included. A summary row shows the latest metric values for the active relation.
