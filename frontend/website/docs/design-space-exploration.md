---
sidebar_position: 5
title: Design Space Exploration
---

# Design Space Exploration

Design space exploration is the first step of the chain: design space exploration, scene generation, trajectory generation, simulation. Scene generation starts from one functional equivalence class (FEC) that you pick or write. This step finds the FECs for you: it takes a specification of the whole design space and a scope, and returns every model of it within the scope. Each model is one FEC, a complete `.problem` text of the kind the [Scene Generation](./scene-generation) page runs.

The page has the list of the FECs found in the centre, the specification editor in the right pane and the step panel at the bottom (Step 1 of 4). The search runs as a job on the active cluster, on a machine that offers design space exploration, and every run is saved as a workbench entry of [Campaign History](./campaign-history) (see [Workbench pages and entries](./workbench-pages)).

## Right pane: the specification

The editor holds the metamodel and the well-formedness constraints: the first part of a FEC specification, with the classes and relations, the error constraints every scene must satisfy, and the lines that pin the own ship. Every model of it within the scope is one FEC.

The control node ships a default specification, and an empty editor starts from it, together with the default scope when the scope is still empty. The default pins the own ship: without that, every FEC would come once per vessel type that can be the own ship, and the same encounter would be listed several times. Pinning it makes each encounter one FEC.

| Control | Description |
|---------|-------------|
| Load the default | Puts the control node's default specification and scope into the editor. It asks first when the editor holds other text. Off while the default is being read, or when the control node ships none (an older control node); then write the specification or open a file |
| Open file... | Loads a `.problem` file from your computer |
| Export the specification (.problem) | The button with the download icon: downloads the text |

The editor is read only while an exploration runs.

### Text or graph

A switch above the editor, **Text** and **Graph**, shows the specification either as text or as a graph of its metamodel. The page remembers the choice in this browser, and the campaign wizard's exploration page has the same switch. The tools of the editor stay in reach in both views, and the graph follows the text a moment after it changes.

The metamodel graph is a class diagram, drawn from whatever the specification declares; nothing in it depends on the names of the default specification:

- A card per class, in the look of Refinery's own graph view: a dark outline, the class's name on a colored header, and under it its attributes and the features whose type is an enum. An abstract class has its name in italics and says "abstract". A class the text uses (as a type or a superclass) without defining it gets a dashed card.
- A card per enum, with a red header and its literals under it.
- Superclasses are above their subclasses. A class may extend several.
- Above the graph, one line counts the classes, enums, predicates and constraints (the `error` predicates) and names the other declarations, such as datatypes, functions or rules. **Show the predicates and constraints** lists them by name with their parameters and their line; their bodies stay in the text.

**Show the legend** under that line explains the lines:

| Line | Meaning |
|------|---------|
| Line with a hollow triangle | `extends`: from a class to its superclass |
| Line with an arrowhead | A reference, labelled with its name and its multiplicity as written, such as `headOn [0..*]` |
| Line with a filled diamond | Containment (`contains` or `container`): the diamond is at the class that contains |
| Line with an arrowhead at both ends | Two references that are each other's `opposite`: one line, each name next to the class it leads to. A reference that is its own opposite is a loop with an arrowhead at both ends |

A reference from a class to itself is a loop on the right side of its card. Hold the pointer over a label for the reference in a sentence. Zoom with the wheel or the buttons at the bottom left, and drag to pan; the graph fits the pane when it changes.

When the text has syntax errors, a line above the graph says how many and on which line the first one is, and the graph shows what could be read. An empty editor shows "Nothing to draw".

## Scope

The scope says how many objects of each class a model has. It is a comma separated list of entries, each `<class> = <count>` or `<class> = <lower>..<upper>`:

| Scope | Meaning |
|-------|---------|
| `TS = 2, StaticObstacle = 0` | Two target ships and no static obstacle |
| `TS = 1..2, StaticObstacle = 0..1` | One or two target ships, with or without one static obstacle |

The field checks the scope as you type, and its message names the entry that is wrong and the form it should have. It reports an empty entry, an entry without `=`, an entry that does not start with a class name, a class given twice, a count that is neither a whole number nor a range, and a range whose lower bound is above the upper one. A scope that is not valid keeps **Explore** off, and the button's tooltip gives the reason. The control node checks the scope again when the run starts.

## Bottom panel

The header holds the status and the run button. The status reads No input yet, Input incomplete, Ready to explore, Exploring, "N FECs found" or "No FEC found".

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

The objects of an explored FEC have the names the catalog uses: the own ship is `os` as the specification pins it, the target ships are `ts1`, `ts2` and so on, and the static obstacles `obst1`, `obst2`. The generator itself names an object after its class with the first letter in lower case (`tS1`, `staticObstacle1`); the exploration renames those in the model, and leaves the specification part of the text as you wrote it. Objects of a class of your own keep the generator's form, with the leading capitals of the class in lower case. A FEC explored before this renaming keeps its old names and still has the vessel's color in the graph.

Below the line is the list of FECs. A row shows the FEC's id (such as `explored/00003`), its vessel and obstacle counts and, once its text is read, its relations in words: every link between two objects, named as the specification names its relation, with camelCase and underscores read as words. `overtakingToPort(ts1, os).` reads "ts1 overtaking to port os", a link that holds both ways is said once ("os and ts1 head on"), and an unknown link (`?`) ends with "(possibly)". Values, such as the vessel type of the own ship, are left out of the row; the graph shows them. A FEC without any link reads "no relations". The texts are read for the rows in view.

Select a row with the mouse, or move the selection with the arrow keys: the selected FEC is shown beside the list. A switch, **Graph** and **Text**, shows it as its model graph (the first time) or as its whole specification, read only; the page remembers the choice.

The model graph draws the objects of the FEC and the facts about them, not the metamodel its text repeats:

- A card per object, as in Refinery's graph view: the object's id on a colored header, then a row with a tag for each class it is (`OS(os).`), a row in italics for each other fact about it alone, and a row for each value: an enum literal it is linked to (`vesselType: OSPassengerShip`) or an attribute's value (`size: 3`). A "?" marks what may hold.
- A vessel has the color it has everywhere else in the console: `os`, `ts1`, `ts2` and so on are the colors of the encounter view and of the paper's figures. Any other object takes a color by the place of its first class in the specification, so objects of the same class look alike.
- A line per link between two objects, labelled with its relation, from the first object to the second. A link that holds both ways (`headOn(a, b). headOn(b, a).`) is one line with an arrowhead at both ends, and an unknown link is dashed.
- The object with the most links is in the middle, the others around it by how many links away they are, with room between them for the names of the links.
- Left out: `default` lines and negative facts (they say what does not hold), the `X::new` objects that stand for further objects of a class, the built-in `exists` and `equals`, and facts about more than two objects, which the line above the graph counts.

The same notice about syntax errors as on the metamodel graph applies.

## Export

The download button in the Result row saves the text of every FEC found as a ZIP of `.problem` files, one per FEC (`explored_00003.problem`). It is off while the exploration runs and while the texts are being read, and when no FEC was found.

## Handing a FEC to Scene Generation

A found FEC becomes the input of Scene Generation in one click, in three places:

- **Next: Scene Generation** on this page takes the selected FEC.
- **Exploration page** on the Input row of the [Scene Generation](./scene-generation) page takes the FEC this page has selected (or its first).
- The exploration's tab in [Campaign History](./campaign-history) lists the FECs, each with **To scene generation**.

The FEC arrives in the Scene Generation editor under a label such as `explored/00003`, and the scene page generates it like any FEC written there.

An exploration saved as an entry is opened again with **Open in workbench** in Campaign History: the page shows its FECs with the chosen one selected, and the specification, scope and limits of the entry are put into the page's input, so the run can be repeated or changed.
