---
sidebar_position: 5
title: Scene Generation
---

# Scene Generation

Scene Generation combines a central 3D/nautical canvas with a right sidebar for functional specification editing and a bottom toolbar for generation actions.

## Right sidebar: Functional Scenario Specification

A CodeMirror editor with Refinery `.problem` language support holds the functional scenario specification. The functional scenarios to start from are the master's catalog (`backend/assets/generated_functional_models/all/`, read through the active cluster), so every browser offers the same ones. Above the editor:

- **Search presets**: Filter the master's functional scenarios by FEC id
- **Vessel / obstacle filters**: Narrow them by actor counts
- **Single scene generation** tab: Load one into the editor, edit inline, load from file, export, or open in [Refinery](https://refinery.services/) (copies spec to clipboard). The list shows the scenario the editor holds, or "Load preset…" when the editor holds another one or an edited text, so any listed scenario can be picked, also the only one a filter leaves. Generating waits until a picked scenario has loaded
- **Batch scene generation** tab: Select several, visualize individual results, download valid scenes as ZIP, open one in Refinery. **Select all shown** adds the listed scenarios to the selection; selected scenarios a filter hides stay selected and run too, and the tab says how many

When the page loads a generated scene (a batch result, or an output opened from Campaign History), the functional scenario the scene was generated from is loaded into the editor as well: the uploaded or written scenario of a workbench run, or the catalog FEC of a campaign. The domain configuration (COLREGS constants, vessel and obstacle types) is the cluster's; see [Domain Configuration](./domain-configuration.md).

## Scene validity badge

When a scene is displayed, a status badge indicates whether it is *valid* (complies with specification) or *invalid* (generation still in progress).

## Bottom toolbar

| Control | Description |
|---------|-------------|
| Live preview | When checked, streams intermediate visualization frames during generation |
| Timeout (s) | Maximum wait time for scene generation (1–86400 seconds) |
| Generate scene / Generate N scenes | Runs the scene generation as a workbench entry on the active cluster (see [Workbench pages and entries](./workbench-pages)). A batch is one entry with a case per scenario, submitted at once, so every free slot is used and the rest wait in the queue. Requires the cluster's domain configuration, a functional spec and a machine that offers scene generation. |
| Stop | Stops the generation and its entry |
| Next: Trajectory Generation | Makes the shown valid scene the input of the Trajectory Generation page and opens it |
| Load Scenario File… | Shows a scenario file's scene and judges it with the cluster's monitor; the scene is no entry |
| Load for Simulation | Makes a scenario file with full trajectories the input of the Simulation page (requires the connected gateway) |
| Export Scenario | Downloads the current visualized scene as JSON |

Status lines show the scenario the page generates from, the entry the page shows, and what the cluster offers (slots on machines, free). Without a machine that runs scene generation, the toolbar says why and generation stays off. A generated scene is judged by the scene monitor when a machine offers monitoring; its verdicts are shown with the scene.

Clicking a batch result shows that case of the batch entry.
