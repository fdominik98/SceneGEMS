---
sidebar_position: 18
title: Capabilities
---

# Capabilities

The Capabilities page shows what the system can run today, what was measured about it, and the generic structure new parts plug into. It needs a selected cluster: the master builds the descriptions from its code, so a new simulator or generator appears here after the master restarts.

## Parts and views

The tabs choose a part of the system, such as the vessel stack, trajectory generation, scene generation or monitoring. Each part has these views:

| View | What it shows |
|------|---------------|
| Implemented | A graph of what exists now and the adapters between the parts |
| Metamodel | A graph of the generic layers and interfaces a new part has to fill in |
| Matrix | Every combination and what it allows, for a part with combinations (the vessel stack) |

The page remembers the part and the view in this browser.

## The graphs

The cards stand in columns, one per layer of the part. An arrow is an adapter or a link between two cards, and its line says what it is: a solid line is an adapter, a dashed one an alternative adapter, a dotted one is planned. A value on a card with a dot was measured; the others are declared. **Show ruled-out connections** adds the connections that cannot exist, each with the reason.

Clicking a card or an arrow opens it in the panel beside the graph; with nothing selected, the panel summarizes the part. A selection shows:

- On **Implemented**: its values, its ports and, for a card of the vessel stack, the stacks it is part of. The path through the selection is highlighted in the graph.
- On **Metamodel**: what an implementation or an adapter must provide, how to add one and where it is defined.

Drag the cards to rearrange them; the arrangement is kept in this browser, and the legend offers to reset it. The wheel zooms, dragging the background pans, and the small map and the buttons in the corners help you find your way. **Full screen** gives the graph and its panel the whole screen, and Escape leaves it.

## The matrix

Each row is an ASV software on a control layer, and each column a simulation layer under it. A cell says whether the stack is **available** or **not possible**, with the reason. An available stack also shows whether it runs as a cluster job (and on which runner) or as a live session only, its repeatability, and what it supports, such as wind and waves. The values of a stack are the weakest link over its layers and adapters.
