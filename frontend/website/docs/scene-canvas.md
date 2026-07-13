---
sidebar_position: 8
title: Scene canvas & visualization
---

# Scene canvas & visualization

The scene canvas renders vessel trajectories, safety domains, and velocity vectors. It supports two view modes toggled via the button in the lower-left corner:

- **Cartesian Canvas**: Three.js orthographic-style top-down view with pan (left mouse), zoom (middle mouse), and axis rulers showing X/Y bounds in meters
- **Nautical GPS**: Leaflet map with WGS84 coordinates anchored to the configured geofence center

## Dual data streams

In Simulation mode, two independent streams may be shown simultaneously with distinct colors:

- **Preview (animation)**: Monitor/preview trajectory from scene generation or playback
- **Simulation**: Live simulation frames from WARA-PS agents

Layer visibility for each stream is controlled in the monitoring sidebar.

## Overlay layers

Per stream, these layers can be toggled independently:

| Layer | Description |
|-------|-------------|
| Dot | Vessel position markers scaled to ship dimensions |
| Velocity | Velocity vector arrows |
| Safety radius ring | Circular safety envelope around each actor |
| Trajectory | Historical path polyline |
| Safety Domains | COLREGS safety domain polygons |

## Recenter control

The axis legend area includes a recenter action. In Cartesian mode it fits the camera to all actors (centered on the own ship when present). In nautical mode it re-centers the map on the geofence.

## Export toolbar

- **Screenshot**: Captures the current canvas as PNG
- **CSV**: Exports frame data as comma-separated values
- **GeoJSON**: Exports trajectory geometry for GIS tools

Export targets the active stream: preview/animation frames in Animation mode, simulation frames in Simulation mode, or the generated scene in Scene Generation mode.
