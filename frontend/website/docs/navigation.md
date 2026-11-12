---
sidebar_position: 3
title: Left navigation menu
---

# Left navigation menu

Expand the menu with the hamburger (☰) button when the left pane is collapsed. From top to bottom it holds the active cluster with its status, the menu items and the footer.

## Active cluster and its status

- **Active cluster**: the cluster every page works on. Without one the workbench stays disconnected. Add clusters on the [Cluster](./cluster.md) page.
- **Status line**: under the cluster, a colored dot and a line that say how the cluster is doing on every page: **Connected** with the worker nodes online and the slots in use, **Connecting**, **Cannot reach the control node**, or a warning when a worker node is offline or out of date. Click it to open the [Cluster](./cluster.md) page. While the menu is collapsed only the dot is left, with the same words as its tooltip.

## Menu items

A mark at the right of an item tells what it holds now:

- On the four workbench steps: a pulsing dot while the page runs, follows or loads a run, a red dot after a failure, and a blue dot while the page shows a result.
- On **Campaign History**: the number of entries that are running.

**Workbench**

- **Design Space Exploration**: Find the FECs of a specification ([Design Space Exploration](./design-space-exploration.md)).
- **Scene Generation**: Author FEC specifications and generate scenes ([Scene Generation](./scene-generation.md)).
- **Trajectory Generation**: Plan the vessel routes ([Trajectory Generation](./trajectory-generation.md)).
- **Simulation**: Run a scenario, watch it play and monitor it ([Simulation view](./simulation.md)).
- **Connections**: the MQTT broker of live simulation sessions, and the geofence ([Connections](./connections.md)).

**Cluster**

- **Cluster**: the machines of the selected cluster and what each one runs ([Cluster](./cluster.md)).
- **Domain Configuration**: the COLREGS constants, vessel types and obstacle types of the cluster ([Domain Configuration](./domain-configuration.md)).
- **Capabilities**: what the system can run ([Capabilities](./capabilities.md)).
- **Campaigns**: define and start a campaign ([Campaigns](./campaigns.md)).
- **Campaign History**: every campaign and workbench run, with its outputs ([Campaign History](./campaign-history.md)).
- **Results**: the findings of an entry ([Results](./results.md)).

## Footer

- **About SceneGEMS**: one line on what the console is for.
- **Light mode** or **Dark mode**: Switches the console to that color mode. The console starts in light mode and keeps your choice per browser.
- **Documentation**: This reference (served at `/docs/`).

When the window is too short for the whole menu, only the menu items scroll: the cluster and the footer stay in view, and the hints under the item names are left out.

The active view and the color mode are remembered across browser sessions. When simulation initializes successfully, the app automatically switches to the Simulation view.
