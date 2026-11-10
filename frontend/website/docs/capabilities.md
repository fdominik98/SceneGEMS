---
sidebar_position: 18
title: Capabilities
---

# Capabilities

The Capabilities page shows how a scenario is made and run, what each part of the system can do today and what was measured about it. It needs a selected cluster: the control node builds the descriptions from its code, so a new simulator, generator or step appears here after the control node restarts.

## The overview

The page opens on **Overview**. It draws the chain, one card per step in the order the steps run:

| Step | Takes | Gives |
|------|-------|-------|
| Design space exploration | a specification and a scope | FECs |
| Scene generation | a FEC | a scene |
| Trajectory generation | a scene | trajectories |
| Simulation, done by the vessel stack | trajectories | a simulated run |

An arrow between two cards names what the first step hands to the next. **Monitoring** stands under the chain, since it judges the scenes, the trajectories and the runs alike.

Each card says:

- what the part is, in a few lines;
- what it takes and what it gives;
- the cluster job that runs it;
- **On this cluster**: how many slots on how many machines of the selected cluster run that job now. "no machine offers it" means that a workbench run or a campaign step of this kind has nowhere to run until a machine with the component joins;
- how many implementations are described and how many values were measured.

**Open** shows the part. A control node from before the overview states no chain: the page then lists the parts side by side without arrows.

## A part and its views

Each part has a tab of its own and these views:

| View | What it shows |
|------|---------------|
| Implemented | A graph of what exists now and the adapters or data between the implementations |
| Metamodel | A graph of the generic structure a new implementation has to fill in |
| Matrix | Every combination and what it allows, for a part with combinations (the vessel stack) |

The line beside the view buttons says what the shown view is for. The page remembers the tab and the view of each part in this browser.

## The graphs

The cards stand in columns, one per layer of the part. An arrow is an adapter or a link between two cards, and its line says what it is: a solid line is an adapter, a dashed one an alternative adapter, a dotted one is planned. A value on a card with a dot was measured; the others are declared. **Show ruled-out connections** adds the connections that cannot exist, each with the reason.

Clicking a card or an arrow opens it in the panel beside the graph. With nothing selected, the panel summarizes the part: what it takes and gives, its counts, and its notes behind **Notes on this part**. A selection shows:

- On **Implemented**: its values, its ports and, for a card of the vessel stack, the stacks it is part of. The path through the selection is highlighted in the graph.
- On **Metamodel**: what an implementation or an adapter must provide, how to add one and where it is defined.

Drag the cards to rearrange them; the arrangement is kept in this browser, and the legend offers to reset it. The wheel zooms, dragging the background pans, and the small map and the buttons in the corners help you find your way. **Full screen** gives the graph and its panel the whole screen, and Escape leaves it.

## The matrix

Each row is an ASV system on a control layer, and each column a simulation layer under it. A cell says whether the stack is **available** or **not possible**, with the reason. An available stack also shows whether it runs as a cluster job (and on which runner) or as a live session only, its repeatability, and what it supports, such as wind and waves. The values of a stack are the weakest link over its layers and adapters.
