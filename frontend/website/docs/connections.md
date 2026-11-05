---
sidebar_position: 7
title: Connections
---

# Connections

The Connections page holds the MQTT broker that live simulation sessions run over: simulated vessels, ArduAgent, real vessels and the live COLREGS monitor meet there. Scene generation, trajectory generation, monitoring and kinematic simulations run as jobs on the active cluster and do not need it.

## Broker

| Field | Description |
|-------|-------------|
| Broker | **Master broker (default)**: the master's own cluster broker, which the server names; nothing else to fill in. **broker.waraps.org over TLS**: the public broker, for real vessels and external agents. **Other broker**: any broker you type in. |
| User / Password | MQTT credentials of an external broker |
| Broker host (as the server dials it) / (as the simulation's containers dial it) | Usually the same host. A broker on `localhost` is reached through the master's Docker host. |
| Port | Broker port (1-65535) |
| TLS connection / Allow certificates | MQTT over TLS, and whether self-signed certificates are accepted |
| Connect / Disconnect | Connect needs the server connection. Disconnect ends the session's broker connection. |

The status line shows the server connection, the broker connection and, once connected, the live monitor. The workbench connects on its own with the saved broker when the server connection comes up, and starts the live monitor with the domain's COLREGS constants once the broker is connected. A real vessel must reach the broker: over the VPN for the master broker, or over the internet for an external one.

## Reference geofence map

A Leaflet map for the WGS84 reference area. Click **Select Geofence**, click the center on the map, then click again to set the radius; Escape cancels and **Reset to default** restores the default area. The geofence center is the origin of the scenario's local frame on the nautical map and for the agents' positions.
