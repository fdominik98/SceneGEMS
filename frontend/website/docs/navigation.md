---
sidebar_position: 3
title: Left navigation menu
---

# Left navigation menu

Expand the menu with the hamburger (☰) button when the left pane is collapsed. Menu items appear in this order:

1. **Workbench**, with its views:
   - **Scene Generation**: Author functional specs and generate scenes.
   - **Trajectory Generation**: Plan the vessel routes.
   - **Simulation**: Run playback and live simulation with monitoring.
   - **Connections**: the MQTT broker of live simulation sessions, and the geofence.
2. **Cluster**: the machines of the selected cluster and what each one runs ([Cluster](./cluster.md)).
3. **Domain Configuration**: the COLREGS constants, vessel types and obstacle types of the cluster ([Domain Configuration](./domain-configuration.md)).
4. **Capabilities**: what the system can run.
5. **Campaigns**: define and start a campaign ([Campaigns](./campaigns.md)).
6. **Campaign History**: every campaign and workbench run, with its outputs ([Campaign History](./campaign-history.md)).
7. **Results**: the findings of an entry.
8. **Documentation**: This reference (served at `/docs/`).

The active view is remembered across browser sessions. When simulation initializes successfully, the app automatically switches to the Simulation view.
