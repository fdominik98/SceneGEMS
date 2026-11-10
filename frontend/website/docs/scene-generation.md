---
sidebar_position: 5
title: Scene Generation
---

# Scene Generation

Scene Generation is step 2 of 4 of the workbench chain, after [Design Space Exploration](./design-space-exploration). It combines the central [scene canvas](./scene-canvas) with a right pane for the FEC specification and a bottom panel for the run.

## Right pane: FEC specification

Each functional scenario specification is one functional equivalence class (FEC). A CodeMirror editor with Refinery `.problem` language support holds the specification. The FECs to start from are the master's catalog (`backend/assets/generated_functional_models/all/`, read through the active cluster), so every browser offers the same ones. Above the editor:

- **Find a FEC**: Filter the master's FECs by FEC id, vessel count and obstacle count
- **Single scene** tab: Load a FEC into the editor from the list, or edit inline. A FEC found on the Design Space Exploration page arrives here too, under a label such as `explored/00003`. **Files and editor tools** loads a file from your computer, exports the text, or opens it in [Refinery](https://refinery.services/) (copies the specification to the clipboard). The list shows the FEC the editor holds, or "Load FEC…" when the editor holds another one or an edited text, so any listed FEC can be picked, also the only one a filter leaves. Generating waits until a picked FEC has loaded
- **Batch (several FECs)** tab: Select several, visualize individual results, **Export all valid** scenes as a ZIP archive, open one in Refinery. **Select all shown** adds the listed FECs to the selection; selected FECs a filter hides stay selected and run too, and the tab says how many

The **Monitor preview** tab of the pane replaces the editor with the [frame data](./monitoring#frame-data) of the shown scene.

When the page loads a generated scene (a batch result, or an output opened from Campaign History), the FEC the scene was generated from is loaded into the editor as well: the uploaded or written specification of a workbench run, or the catalog FEC of a campaign. The domain configuration (COLREGS constants, vessel and obstacle types) is the cluster's; see [Domain Configuration](./domain-configuration.md).

## Bottom panel

The header holds the step's status and the run button. The status says whether the shown scene is valid (it complies with the specification), or that the generation found none within its timeout, in which case the best attempt is shown.

| Row | Control | Description |
|-----|---------|-------------|
| Header | Generate scene / Generate N scenes | Runs the scene generation as a workbench entry on the active cluster (see [Workbench pages and entries](./workbench-pages)). A batch is one entry with a case per FEC, submitted at once, so every free slot is used and the rest wait in the queue. Requires the cluster's domain configuration, a FEC and a machine that offers scene generation. |
| Header | Stop | Stops the generation and its entry |
| Input | FEC or Batch | The FEC of the run, or how many are selected. **Show the specification** brings the editor back from the monitor preview. **Exploration page** puts the FEC the [Design Space Exploration](./design-space-exploration) page has selected (or its first) into the editor; it is off while that page shows none, and is not offered for a batch |
| Setup | Seed | The base seed of the entry; empty for a random one |
| Setup | Timeout | How long one generation may search for a valid scene (1 to 86400 seconds) |
| Setup | Low TCPA | Generates the COLREGS situation with a low time to the closest point of approach |
| Setup | Live preview | Draws the scenes the search tries on the canvas while it runs |
| Result | Open file... | Shows a scenario file's scene and judges it with the cluster's monitor; the scene is no entry |
| Result | Export the scene (JSON) | Downloads the shown valid scene as JSON (the button with the download icon) |
| Result | Next: Trajectory Generation | Makes the shown valid scene the input of the Trajectory Generation page and opens it |

The panel says what the cluster offers (slots on machines, free) and which entry the page shows. Without a machine that runs scene generation, it says why and generation stays off. A generated scene is judged by the scene monitor when a machine offers monitoring; its monitor result summaries are shown with the scene.

Clicking a batch result shows that case of the batch entry.
