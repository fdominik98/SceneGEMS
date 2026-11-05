---
sidebar_position: 11
title: Metrics & analysis
---

# Metrics & analysis

The **Charts** tab of the [monitoring panel](./monitoring) shows COLREGS metric time-series charts for the selected vessel pair, for the stream the panel shows.

## Relation selector

**Relation** lists the vessel pairs in the stream. Changing the selection updates the table and all charts together.

## Latest values

A table shows the latest value of each metric for the selected pair.

## Charts

| Chart | Description |
|-------|-------------|
| Distance | Range between the vessels over time, in meters |
| DCPA | Distance at closest point of approach, in meters |
| TCPA | Time to closest point of approach, in seconds |
| DS index | COLREGS danger-sector index, from 0 to 1 |

The charts and the table follow the playhead: only frames at or before the current time are included. Hover over a chart to read a value. The wheel zooms a chart around the pointer, a zoomed chart can be dragged, and **Reset zoom** brings the whole series back.
