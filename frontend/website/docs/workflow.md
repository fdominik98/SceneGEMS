---
sidebar_position: 16
title: Typical workflow
---

# Typical workflow

A recommended end-to-end flow for exploring a maritime scenario:

1. **Select the cluster**: choose the active cluster in the left pane; the workbench runs its jobs there and talks to its master's gateway
2. **Check the domain**: Open Domain Configuration in the Cluster group; review or edit the COLREGS constants, vessel types and obstacle types of the cluster and save them (every run on the cluster uses them)
3. **Generate a scene**: Open Scene Generation, search the master's functional scenarios, load one into the editor (or write or load a `.problem` spec), click Generate scene. The run is saved as an entry of Campaign History.
4. **Plan trajectories**: click Next: Trajectory Generation (the scene becomes the page's input), choose the generator and click Generate Trajectories
5. **Simulate**: click Next: Simulation (the trajectories become the simulation page's input), set up the vessels and click Run on the cluster, or Initialize and Start for a live session
6. **Connections** (live sessions only): set the geofence and connect the MQTT broker; the master's broker is the default and connects on its own
7. **Monitor & analyze**: Use the monitoring sidebar for layer control, actor info, and COLREGS metrics; toggle Overall analysis for charts
8. **Come back to any output**: Campaign History lists every run; Open in workbench shows an output on its page, and any page can take a history output as its input
9. **Record & export**: Record trajectories, export JSON/CSV/GeoJSON, or capture screenshots for reports

For batch evaluation, use the Batch scene generation tab: the selected functional scenarios run as one entry with a case per scenario, and valid results export as a ZIP archive. For campaign runs that come up again and again, start the campaign wizard from one of the master's [campaign presets](./campaign-wizard.md#presets).
