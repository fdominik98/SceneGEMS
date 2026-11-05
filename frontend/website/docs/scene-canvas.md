---
sidebar_position: 8
title: Scene canvas & visualization
---

# Scene canvas & visualization

The scene canvas draws the vessels, their tracks, course vectors and safety domains as a chart. It has two views, switched with the map button in its toolbar:

- **Encounter canvas**: A chart of the scenario's local frame. Drag pans, the wheel zooms around the pointer, and a double-click or **Fit view** recenters
- **Nautical map**: The same layers over the OpenStreetMap tiles and the OpenSeaMap seamarks, placed by the reference geofence of the [Connections](./connections) page. It is always north up

In dark mode the chart is a night chart: a dark sea, with the map's tiles darkened to match. In light mode it is a day chart: pale water and dark marks, with the map's tiles as published. Each vessel keeps its hue in both modes.

## Toolbar

| Button | What it does |
|--------|--------------|
| Fit view | Recenters with every vessel in sight |
| North up or head up | Encounter canvas only: turns the chart so the own ship's heading is at the top, or back to north. Head up needs an own ship |
| Layers | Opens the [layer menu](#layers) |
| Export | Opens the [export menu](#export) |
| Show nautical map or Show encounter canvas | Switches the view |
| Show monitoring panel | Only while the monitoring panel is hidden |

## Preview and simulation streams

On the Simulation page, two independent streams may be drawn at once:

- **Preview**: The planned trajectories of the page's input
- **Simulation**: Frames of the simulation, from a cluster job or a live session's agents

While both are drawn, the simulation's vessels take a darker shade of the same hue.

## Layers

The **Layers** menu holds every layer of the view, for the encounter canvas and the map alike. Each vessel layer has a switch per stream, so the preview and the simulation are set side by side:

| Layer | Description |
|-------|-------------|
| Visible | The whole stream (on the Trajectory Generation and Simulation pages) |
| Hulls and headings | Vessel outlines, scaled to the ship's dimensions, and their headings |
| Course vectors | Where each vessel will be after the vector length, with a mark each minute |
| Tracks | The path so far, and ahead when a plan or a record has it |
| Safety domains | The COLREGS safety domain of each vessel |
| Maneuvering corridors | The give-way vessel's corridor |
| Static avoidance domains | The domain each vessel keeps from a static obstacle |
| Safety radius rings | A circular safety envelope around each actor |

Under them are the chart's own marks, **Range rings**, **CPA**, **Labels** and **Legend**, and the **Vector length** (1 to 30 minutes). These settings are kept in this browser.

## Selecting a vessel pair

A click near a vessel selects its pair, on the canvas and on the map, and so does a click on the pair's card in the monitoring panel: the chart draws the line between the two vessels, and the card and the rule timeline highlight the pair.

## Export

- **Screenshot (image)**: The encounter canvas as PNG, in the colors of the current mode (not on the map)
- **Table (CSV)**: Frame data as comma-separated values
- **Map data (GeoJSON)**: Trajectory geometry for GIS tools

The menu exports the shown scene on Scene Generation, and the preview's frames on the other pages. For the frames of the simulation, use the export button of the [monitoring panel](./monitoring), which takes the stream it shows.
