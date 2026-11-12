---
sidebar_position: 17
title: Cluster
---

# Cluster

The Cluster page shows the machines of the selected cluster: whether each worker node is online, what it offers and how busy it is, and what it runs right now.

## Clusters

**Manage clusters** lists the control nodes this browser knows (a name and the operator URL, `http://127.0.0.1:5174` by default) and selects the one the cluster pages work on. A remote control node is reached over an SSH tunnel to its operator listener.

## Worker nodes

The tiles count the worker nodes online, the slots in use and the worker nodes whose images differ from the control node's release. Each worker node card shows its state, its machine, its components, the slots in use and, under **Details**, its slots per job type, resources, labels and leases. A worker node runs one long-lived subsystem of each kind its components need, and the slots of a job type are the places in that subsystem's task pool: how many of its jobs the worker node runs at once.

A worker node's capability is a set of components: the vessel stack layers it runs (replay, USV Navigation, no control layer, ArduPilot, the custom controller, the kinematic layer, ArduPilot SITL, Gazebo) and the subsystems (design space exploration, scene generation, trajectory generation, monitoring, calibration). A job runs on a worker node that has slots for its job type and every component it needs: a simulation needs every layer of every vessel's stack, so a Gazebo replay on ArduPilot needs replay, ArduPilot and Gazebo, and USV Navigation on the own ship adds USV Navigation. A simulation that is judged while it runs also needs monitoring on the same worker node and takes a monitoring slot there for as long as it runs, so the card may show a monitoring slot in use without a monitoring job. The custom controller steps the Gazebo world itself, so a worker node with replay, the custom controller and Gazebo, and no ArduPilot SITL, runs it. A component whose images differ from the control node's release is marked **out of date** on the card and gets no jobs there; the worker node's other components keep working. A worker node is out of date as a whole only when all its components are.

| Action | What it does |
|--------|--------------|
| Drain | No new jobs for the worker node; running ones finish. **Resume** lets it take jobs again. |
| Remove | Forgets an offline worker node. It comes back if it connects again. |
| Clear offline | Forgets every offline worker node at once. |

## Instances of a worker node

**Instances** on a worker node card opens the worker node's instances below the cards; the button names how many jobs the worker node holds. The list has two parts:

- **Pools**: one instance per slot of the scene generation and trajectory search pools the worker node offers.
- **Leased jobs**: the jobs the worker node has leased or runs.

Choosing an instance opens its viewer. The control node observes an instance only while a viewer shows it; closing the view, choosing another instance or closing the instances ends the observation.

| Instance | Viewer |
|----------|--------|
| Scene generation | The latest sampled scene with its validity, on the encounter view |
| Trajectory search | The latest trajectory preview, and the result once the search ends |
| Simulation | The frames of the run as they arrive, at the speed chosen in **Watch at** (kinematic and custom controller runs are paced to it; an ArduPilot run plays at it in the browser) |
| Other jobs | The job's status, progress and log. A design space exploration reports how many FECs it has found so far |

To follow a running entry of a campaign or a workbench run, Campaign History's **Watch live** opens it on its workbench page instead.
