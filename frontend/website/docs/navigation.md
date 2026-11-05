---
sidebar_position: 3
title: Left navigation menu
---

# Left navigation menu

Expand the menu with the hamburger (☰) button when the left pane is collapsed. Menu items appear in this order:

**Workbench**

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

Under the menu:

- **Active cluster**: the cluster every page works on. Without one the workbench stays disconnected. It is hidden while the menu is collapsed; add clusters on the [Cluster](./cluster.md) page.
- **Light mode** or **Dark mode**: Switches the console to that color mode. The console starts in dark mode.
- **Documentation**: This reference (served at `/docs/`).

The active view and the color mode are remembered across browser sessions. When simulation initializes successfully, the app automatically switches to the Simulation view.
