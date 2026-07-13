---
sidebar_position: 16
title: Typical workflow
---

# Typical workflow

A recommended end-to-end flow for exploring a maritime scenario:

1. **Start the backend**: Run the Python WebSocket server and confirm `VITE_WS_URL` in `.env`
2. **Configure domain**: Open Domain Configuration; review or edit COLREGS, vessel types, and obstacle types
3. **Generate a scene**: Open Scene Generation, search functional presets, load a `.problem` spec, click Generate Initial Scenes
4. **Initialize scenario**: When the scene is valid, click Initialize Scenario to load it on the backend
5. **Connect WARA-PS**: Open Connect to WARA-PS, set geofence on the map, connect (or rely on auto-connect)
6. **Initialize simulation**: In Simulation view, configure vessel connections and simulation parameters (including simulation speed), click Initialize Simulation, then Start
7. **Monitor & analyze**: Use the monitoring sidebar for layer control, actor info, and COLREGS metrics; toggle Overall analysis for charts
8. **Record & export**: Record trajectories, export JSON/CSV/GeoJSON, or capture screenshots for reports

For batch evaluation, use the Batch scene generation tab to queue multiple functional presets and export valid results as a ZIP archive.
