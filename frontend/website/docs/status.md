---
sidebar_position: 15
title: Status indicators & errors
---

# Status indicators & errors

## Connection statuses

- **Backend socket**: WebSocket link to the Python simulation server (`VITE_WS_URL`)
- **WARA-PS status**: MQTT session state (connected / disconnected / etc.)
- **Monitor status**: COLREGS monitor lifecycle
- **Simulation status**: Agent readiness and execution state

Status text uses color-coded CSS classes for quick visual identification. A global error bar at the bottom of the screen aggregates scene-generation and backend errors; click to dismiss.

## Loading indicators

Spinner overlays appear during domain preset loading, scene generation, and preset catalog loading.
