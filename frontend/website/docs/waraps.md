---
sidebar_position: 7
title: Connect to WARA-PS
---

# Connect to WARA-PS

WARA-PS integration uses MQTT brokers to connect live maritime simulation agents. The view is split into a connection form (left) and an interactive geofence map (right).

## Connection form

| Field | Description |
|-------|-------------|
| Connection profile | Presets: Live MQTT, Local MQTT, or Custom. Selecting a preset fills broker fields. |
| User / Password | MQTT credentials |
| Agent broker / Client broker | MQTT broker URLs for agent and client channels |
| Port | Broker port (1–65535) |
| TLS connection | Enable TLS for MQTT |
| Allow certificates | Accept self-signed or custom certificates |
| Connect / Disconnect | Connect requires an active backend WebSocket. Disconnect ends the WARA-PS session. |

Status indicators show **Backend socket** and **WARA-PS status** separately. The app auto-connects using the saved profile when the backend socket becomes available, and auto-initializes the monitor when WARA-PS connects (if COLREGS config is present).

## Reference geofence map

A Leaflet map for defining the WGS84 reference area. Drag handles to resize the geofence rectangle. The geofence center becomes the origin for nautical map visualization. When a preview own-ship position is available, a hint shows its Cartesian coordinates relative to the scenario frame.
