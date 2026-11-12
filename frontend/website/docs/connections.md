---
sidebar_position: 7
title: Connections
---

# Connections

The Connections page holds two settings a simulation job on a worker node uses: the MQTT broker a real vessel's agent is on, and where the scenario lies on the map. Nothing connects from this page, and the browser never talks to a broker.

Scene generation, trajectory generation, monitoring and simulations without a real vessel need no broker setting: the subsystems of a worker node talk to each other and to its daemon over the cluster's own broker.

## Broker

The broker matters only for a simulation with a real vessel (see [Control panel](./control-panel)).

| Field | Description |
|-------|-------------|
| Broker | **Control node broker (default)**: the control node's own cluster broker, plain MQTT on the cluster's VPN; nothing else to fill in. The agent of a real vessel must reach the control node over the VPN to take part. **broker.waraps.org over TLS**: the public broker, for real vessels and external agents. **Other broker**: any broker you type in. |
| User / Password | MQTT credentials of an external broker |
| Broker host (as the worker node's containers dial it) | The host the job's containers connect to |
| Port | Broker port (1-65535) |
| TLS connection / Allow certificates | MQTT over TLS, and whether self-signed certificates are accepted |

The address fields are under **Broker address** and appear for an external broker. With an external broker, the vessels of a run with a real vessel are all on that broker, and the worker node that runs the job must reach it. The password is sent with the job and is masked wherever the job's payload is shown.

## Reference area (geofence)

A Leaflet map for the WGS84 reference area. Click **Select Geofence**, click the center on the map, then click again to set the radius; Escape cancels and **Reset to default** restores the default area. The geofence center is the origin of the scenario's local frame on the nautical map and for the agents' positions. Every simulation job on ArduPilot SITL or Gazebo, and every run with a real vessel, takes it.
