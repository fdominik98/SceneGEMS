---
sidebar_position: 5
title: Design Space Exploration
---

# Design Space Exploration

Design space exploration is the first step of the chain: design space exploration, scene generation, trajectory generation, simulation. Scene generation starts from one functional equivalence class (FEC) that you pick or write. This step finds the FECs for you: it takes a specification of the whole design space and a scope, and returns every model of it within the scope. Each model is one FEC, a complete `.problem` text of the kind the [Scene Generation](./scene-generation) page runs.

The page has the list of the FECs found in the centre, the specification editor in the right pane and the step panel at the bottom (Step 1 of 4). The search runs as a job on the active cluster, on a machine that offers design space exploration, and every run is saved as a workbench entry of [Campaign History](./campaign-history) (see [Workbench pages and entries](./workbench-pages)).

## Right pane: the specification

The editor holds the metamodel and the well-formedness constraints: the first part of a FEC specification, with the classes and relations, the error constraints every scene must satisfy, and the lines that pin the own ship. Every model of it within the scope is one FEC.

The master ships a default specification, and an empty editor starts from it, together with the default scope when the scope is still empty. The default pins the own ship: without that, every FEC would come once per vessel type that can be the own ship, and the same encounter would be listed several times. Pinning it makes each encounter one FEC.

| Control | Description |
|---------|-------------|
| Load the default | Puts the master's default specification and scope into the editor. It asks first when the editor holds other text. Off while the default is being read, or when the master ships none (an older master); then write the specification or open a file |
| Open file... | Loads a `.problem` file from your computer |
| Export the specification (.problem) | The button with the download icon: downloads the text |

The editor is read only while an exploration runs.

## Scope

The scope says how many objects of each class a model has. It is a comma separated list of entries, each `<class> = <count>` or `<class> = <lower>..<upper>`:

| Scope | Meaning |
|-------|---------|
| `TS = 2, StaticObstacle = 0` | Two target ships and no static obstacle |
| `TS = 1..2, StaticObstacle = 0..1` | One or two target ships, with or without one static obstacle |

The field checks the scope as you type, and its message names the entry that is wrong and the form it should have. It reports an empty entry, an entry without `=`, an entry that does not start with a class name, a class given twice, a count that is neither a whole number nor a range, and a range whose lower bound is above the upper one. A scope that is not valid keeps **Explore** off, and the button's tooltip gives the reason. The master checks the scope again when the run starts.

## Bottom panel

The header holds the status and the run button. The status reads Idle, Exploring, "N FECs found" or "No FEC found".

| Row | Control | Description |
|-----|---------|-------------|
| Header | Explore | Starts the exploration as a workbench entry. Needs a specification, a valid scope and a machine that offers design space exploration |
| Header | Stop | Stops the exploration |
| Input | Specification | What the editor holds (its source and its number of lines). **Edit in the specification pane** puts the cursor in the editor |
| Input | Scope | The scope field described above |
| Setup | Seed | The base seed of the entry; empty for a random one (see [Every run is an entry](./workbench-pages#every-run-is-an-entry)) |
| Setup | Max FECs | Stops the search after this many FECs. Empty explores every FEC of the scope. The default is 1000 |
| Setup | Timeout | How long the search may run (1 to 86400 seconds); the FECs found until then are kept. The default is 600 seconds |
| Result | FECs | What was found and what that means (see below), or the progress while it runs, and the link of the page's entry to Campaign History |
| Result | Export the FECs (ZIP of .problem files) | The button with the download icon: downloads the text of every FEC found as a ZIP of `.problem` files |
| Result | Next: Scene Generation | Puts the selected FEC (the first one when none is selected) into the Scene Generation page's editor and opens that page |

The page remembers its specification, scope, Max FECs and Timeout in this browser.

### What blocks a run

When something blocks the run, the panel lists the reason under the header and **Explore** stays off: no active cluster is selected, the active cluster cannot be reached, or no machine of the active cluster offers design space exploration (or the machines that do are offline, draining or out of date). Without a specification, or with a scope that is not valid, the button's tooltip says what to correct.

## Running

While the search runs, the Result row shows the message of the job and, once the job reports one, a bar with the share of the cap found. The centre says that the design space is being explored; the FECs are listed once the exploration ended. The inputs are off until then. **Stop** ends the search.

## Reading the result

The centre starts with one line that says how many FECs were found and why the search ended:

| Stop reason | What the line says |
|-------------|--------------------|
| Exhausted | "N FECs: all FECs of the design space." The scope has no more |
| No model | "No FEC: the specification has no model within the scope." Change the specification or widen the scope |
| Cap reached | "The first N FECs: the cap of M was reached, there may be more." Raise Max FECs, or empty it, to find the rest |
| Timeout | "The first N FECs: the time limit ended the search, there may be more", or "No FEC" when the limit came before the first one |
| Stopped | "The first N FECs: the search was stopped, there may be more", or "No FEC" when the stop came before the first one |

Without a cap the exploration returns every FEC of the scope; with a cap or a time limit it returns the FECs found until then and says so. On the default specification, one target ship gives 7 FECs, two give 28, and two with one static obstacle also give 28, each in about 6 seconds.

Below the line is the list of FECs. A row shows the FEC's id (such as `explored/00003`), its vessel and obstacle counts and, once its text is read, its relations in words, for example "a overtakes b to port" or "a and b head-on". The relations are the COLREGS relations between the vessels (head-on, overtaking to port or to starboard, crossing from port) and the obstacles in the dangerous head-on sector of a vessel; a FEC without any reads "no relations". The texts are read for the rows in view. Select a row with the mouse, or move the selection with the arrow keys: the whole specification of the selected FEC is shown read only beside the list.

## Export

The download button in the Result row saves the text of every FEC found as a ZIP of `.problem` files, one per FEC (`explored_00003.problem`). It is off while the exploration runs and while the texts are being read, and when no FEC was found.

## Handing a FEC to Scene Generation

A found FEC becomes the input of Scene Generation in one click, in three places:

- **Next: Scene Generation** on this page takes the selected FEC.
- **Exploration page** on the Input row of the [Scene Generation](./scene-generation) page takes the FEC this page has selected (or its first).
- The exploration's tab in [Campaign History](./campaign-history) lists the FECs, each with **To scene generation**.

The FEC arrives in the Scene Generation editor under a label such as `explored/00003`, and the scene page generates it like any FEC written there.

An exploration saved as an entry is opened again with **Open in workbench** in Campaign History: the page shows its FECs with the chosen one selected, and the specification, scope and limits of the entry are put into the page's input, so the run can be repeated or changed.
