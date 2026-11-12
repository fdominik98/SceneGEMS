---
sidebar_position: 12
title: Recording & export
---

# Recording & export

There is nothing to start or stop: every run is recorded as an entry of [Campaign History](./campaign-history).

- **A run on the cluster** is saved as a workbench entry, with its outputs.
- **An attended run** (a real vessel, Mission Planner) is a run on the cluster too, and is saved the same way.

## Replay

**Open in workbench** in Campaign History loads an output on the page of its step; a simulated run loads as a replay of its frames with the monitor. A page can also take a file as its input with **File...**. See [Workbench pages and entries](./workbench-pages).

## Export

| What | Where | Format |
|------|-------|--------|
| A FEC specification | Scene Generation, **Files and editor tools**, **Export** | `.problem` |
| The shown scene | Scene Generation, Result row | JSON |
| The valid scenes of a batch | Scene Generation, Batch results, **Export all valid** | ZIP of JSON files |
| The planned trajectory | Trajectory Generation, Result row | JSON |
| The frames of the shown stream | Monitoring panel, the export button beside the stream | JSON |
| The canvas | Canvas toolbar, **Export**, **Screenshot (image)** | PNG, in the colors of the current mode |
| The frames as a table | Canvas toolbar, **Export**, **Table (CSV)** | CSV |
| The frames as map data | Canvas toolbar, **Export**, **Map data (GeoJSON)** | GeoJSON |
| The monitor result summaries of an entry | [Results](./results), the table's download | CSV |
