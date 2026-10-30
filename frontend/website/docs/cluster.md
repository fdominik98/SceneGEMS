---
sidebar_position: 17
title: Cluster
---

# Cluster

The Cluster page shows the machines of the selected cluster: whether each node is online, what it offers and how busy it is, and what it runs right now.

## Clusters

**Manage clusters** lists the masters this browser knows (a name and the operator URL, `http://127.0.0.1:5174` by default) and selects the one the cluster pages work on. A remote master is reached over an SSH tunnel to its operator listener.

## Nodes

The tiles count the nodes online, the slots in use and the nodes whose images differ from the master's release. Each node card shows its state, its machine, its components, the slots in use and, under **Details**, its slots per job type, resources, labels and leases.

A node's capability is a set of components: the vessel stack layers it runs (replay, USV Navigation, no control layer, ArduPilot, the custom controller, the kinematic layer, ArduPilot SITL, Gazebo) and the subsystems (scene generation, trajectory generation, monitoring, calibration). A job runs on a node that has slots for its job type and every component it needs: a simulation needs every layer of every vessel's stack, so a Gazebo replay needs replay, ArduPilot and Gazebo. A component whose images differ from the master's release is marked **out of date** on the card and gets no jobs there; the node's other components keep working. A node is out of date as a whole only when all its components are.

| Action | What it does |
|--------|--------------|
| Drain | No new jobs for the node; running ones finish. **Resume** lets it take jobs again. |
| Remove | Forgets an offline node. It comes back if it connects again. |
| Clear offline | Forgets every offline node at once. |

## Instances of a node

**Instances** on a node card opens the node's instances below the cards; the button names how many jobs the node holds. The list has two parts:

- **Pools**: one instance per slot of the scene generation and trajectory search pools the node offers.
- **Leased jobs**: the jobs the node has leased or runs.

Choosing an instance opens its viewer. The master observes an instance only while a viewer shows it; closing the view, choosing another instance or closing the instances ends the observation.

| Instance | Viewer |
|----------|--------|
| Scene generation | The latest sampled scene with its validity, on the encounter view |
| Trajectory search | The latest trajectory preview, and the result once the search ends |
| Simulation | The frames of the run as they arrive, at the speed chosen in **Watch at** (kinematic runs are paced to it) |
| Other jobs | The job's status, progress and log |

To follow a running entry of a campaign or a workbench run, Campaign History's **Watch live** opens it on its workbench page instead.
