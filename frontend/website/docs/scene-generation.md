---
sidebar_position: 5
title: Scene Generation
---

# Scene Generation

Scene Generation is step 2 of 4 of the workbench chain, after [Design Space Exploration](./design-space-exploration). It combines the central [scene canvas](./scene-canvas) with a right pane for the FEC specification and a bottom panel for the run.

## Right pane: FEC specification

Each functional scenario specification is one functional equivalence class (FEC). The FECs to start from are the control node's catalog (`backend/assets/generated_functional_models/all/`, read through the active cluster), so every browser offers the same ones. You choose what to generate in one place: the list of the control node's FECs. What a run does follows from what is selected there.

### The list of FECs

**FECs of the control node** lists every catalog FEC, with a search over the FEC id and filters by vessel count and obstacle count (the page remembers them). A row shows the FEC's id, its counts and, once its text is read, its relations in words, such as "os and ts1 head on" (see [Reading the result](./design-space-exploration#reading-the-result) for how they are worded). Only the rows in view are drawn and read, so the whole catalog scrolls smoothly; drag the bottom edge of the list to make it taller.

- The checkbox of a row selects the FEC for the run. **Select all shown** adds the listed FECs to the selection, **Clear** empties it, and the line above the list counts the selected FECs. Selected FECs a filter hides stay selected and run too; the line says how many.
- Clicking the rest of a row previews that FEC below the list without selecting it, so you can see what it is before you tick it. The preview has **Add to the selection** (or **Remove from the selection**) and **Close the preview**.

The page remembers the selection in this browser. A remembered FEC that the control node no longer has is dropped when the catalog is read.

### What the run takes

| Selected | What the pane shows below the list | What **Generate** does |
|----------|------------------------------------|------------------------|
| No FEC | The editor | Generates one scene of the editor's text |
| One FEC | That FEC, read only | Generates one scene of that FEC, under its id |
| Several FECs | How many are selected | Generates a batch: a scene of each FEC, as one entry with a case per FEC |

**No FEC selected: the editor.** A CodeMirror editor with Refinery `.problem` language support holds the specification you write. **Files and editor tools** loads a file from your computer, exports the text, or opens it in [Refinery](https://refinery.services/) (copies the specification to the clipboard). Anything that puts a text into the editor from outside clears the selection, so that the editor shows it: loading a file, a FEC sent from the [Design Space Exploration](./design-space-exploration) page or from Campaign History (it arrives under a label such as `explored/00003`), and **Exploration page** on the bottom panel's Input row.

**One FEC selected.** The pane shows that FEC read only, as its model graph first, with **Edit a copy** and **Open in Refinery**. **Edit a copy** puts the FEC's text into the editor under a label such as `3vessel_0obstacle_scenarios/fec5 (copy)` and clears the selection, so you can change it and generate the changed text.

**Several FECs selected.** The run is a batch. Its results are listed under **Batch results**, a row per FEC with its status; click a valid one to show it on the canvas (its row is marked "visualized"), and **Export all valid** downloads the valid scenes as a ZIP archive. The results stay until the next batch, also when the selection changes.

### Graphs

The editor, the one selected FEC and the preview have a switch, **Graph** and **Text**. The graph is the model graph of the text: a card per object with its classes and values, a line per link between two objects, as described on the [Design Space Exploration](./design-space-exploration#reading-the-result) page. It is drawn from whatever the text declares. The editor's graph follows the text a moment after you type, and a text with syntax errors says how many there are and draws what could be read. The editor starts on Text, a FEC on Graph; the page remembers both choices.

The **Monitor preview** tab of the pane replaces all this with the [frame data](./monitoring#frame-data) of the shown scene.

When the page loads a generated scene opened from Campaign History, the FEC the scene was generated from comes along: a catalog FEC is selected in the list (also for a scene a single run of a selected FEC made), any other specification (written, from a file, explored or an edited copy) goes into the editor. Showing a batch result keeps the selection of the batch. The domain configuration (COLREGS constants, vessel and obstacle types) is the cluster's; see [Domain Configuration](./domain-configuration.md).

## Bottom panel

The header holds the step's status and the run button. The status says whether the shown scene is valid (it complies with the specification), or that the generation found none within its timeout, in which case the best attempt is shown.

| Row | Control | Description |
|-----|---------|-------------|
| Header | Generate scene / Generate N scenes | Runs the scene generation as a workbench entry on the active cluster (see [Workbench pages and entries](./workbench-pages)): **Generate scene** for the editor's text or the one FEC selected, **Generate N scenes** for N selected FECs. A batch is one entry with a case per FEC, submitted at once, so every free slot is used and the rest wait in the queue. Requires the cluster's domain configuration, a FEC and a machine that offers scene generation; a button that is off says in its tooltip what is missing |
| Header | Stop | Stops the generation and its entry |
| Input | FEC or Batch | What the run takes: the label of the editor's text ("written in the editor", "none chosen"), the id of the one FEC selected, or "N FECs selected". **Show the specification** brings the pane back from the monitor preview. **Exploration page** puts the FEC the [Design Space Exploration](./design-space-exploration) page has selected (or its first) into the editor and clears the selection; it is off while that page shows none |
| Setup | Seed | The base seed of the entry; empty for a random one |
| Setup | Timeout | How long one generation may search for a valid scene (1 to 86400 seconds) |
| Setup | Low TCPA | Generates the COLREGS situation with a low time to the closest point of approach |
| Setup | Live preview | Draws the scenes the search tries on the canvas while it runs |
| Result | Open file... | Shows a scenario file's scene and judges it with the cluster's monitor; the scene is no entry |
| Result | Export the scene (JSON) | Downloads the shown valid scene as JSON (the button with the download icon) |
| Result | Next: Trajectory Generation | Makes the shown valid scene the input of the Trajectory Generation page and opens it |

The panel says what the cluster offers (slots on machines, free) and which entry the page shows. Without a machine that runs scene generation, it says why and generation stays off. A generated scene is judged by the scene monitor when a machine offers monitoring; its monitor result summaries are shown with the scene.

Clicking a valid batch result shows that case of the batch entry.
