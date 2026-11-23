# SceneGEMS: Scenario Generation and Execution Framework for the Safety Assurance of Maritime Autonomous Surface Vehicles

SceneGEMS generates COLREGS encounter scenarios, simulates them with pluggable vessel stacks faster than real time and judges every run with a COLREGS monitor. The scene pipeline (functional, logical and concrete level) comes from the paper *Automated Generation of Functionally Complete Assurance Suites for COLREGS-Compliance of Autonomous Surface Vehicles*.

SceneGEMS runs on a cluster: one control node and any number of worker nodes, deployed by Machine Hub (the control node's machine can be your own PC). The web console works on the cluster selected in its left pane:

- **Workbench**: you explore the scenario classes of a specification, design a scenario, generate its scene and trajectories and simulate it interactively. The control node's control-node-api serves the workbench gateway, which only reads scenario files and generates vessel models; everything that computes is a job, which a subsystem on one of the cluster's worker nodes runs.
- **Campaigns**: every scenario class in a campaign's scope, or every class a design space exploration finds, is generated, simulated and monitored automatically; the web console configures, follows and inspects the campaigns.

## Repository layout

| Path | Content |
|------|---------|
| [`backend/`](backend/) | Python package roots under `backend/src/`: `scenegems_tool` (workbench gateway, subsystems, vessel stacks, the cluster's control node and worker node, the assurance pipeline, persistence), `functional_level`, `logical_level`, `concrete_level`, `evaluation`, `visualization`, `scripts`, `utils`, `tests`. Domain configuration, the 828 functional scenario classes and runtime assets are in `backend/assets/` |
| [`frontend/`](frontend/) | React and Vite web console with the sections Workbench, Cluster, Domain Configuration, Capabilities, Campaigns, Campaign History and Results; in-app documentation in `frontend/website/` |
| [`deploy/images/`](deploy/images/) | One folder per Docker image: `control_node_api`, `worker_node`, `mqtt_broker`, the subsystems `design_space_exploration`, `monitoring`, `scene_generation`, `simulation`, `trajectory_generation`, the simulation images `gazebo`, `sitl`, `mavproxy`, `arduagent`, and `usv_navigation` and `moos_ivp`, the images of the USV Navigation and MOOS-IvP ASV systems. `upstream_pins.env` pins the upstream sources of the Gazebo and SITL images, the MOOS-IvP fork commit of the MOOS-IvP image and the Refinery commit and base images of the design space exploration image |
| [`deploy/kubernetes/`](deploy/kubernetes/) | The Helm chart of a cluster (`chart/`: control node, worker nodes, rights, network policy, values schema) and `scripts/local_cluster.sh`, which runs a cluster on this PC in k3d |
| [`deploy/scripts/`](deploy/scripts/) | `build.sh` and its fingerprint and build helpers `docker-common.sh`; `./build.sh` in the repository root calls it |

The images that copy files from `backend/` (control-node-api, subsystems, worker node, Gazebo, SITL) build with the repository root as their Docker context, so their `COPY` lines start with `deploy/images/...` or `backend/...`.

## Requirements

| Requirement | Details |
|-------------|---------|
| Docker | Docker Engine (Docker Desktop on Windows) to build the images and to run a local cluster in k3d |
| Kubernetes tools | For a cluster on this PC and the tests marked `kubernetes`: `k3d` (5.9.0), `helm` (4.3.2, the version Machine Hub pins) and `kubectl` |
| Shell | Bash; on Windows Git Bash or WSL |
| Disk | Several GB for every image (Gazebo and SITL are the largest); less with `./build.sh --backend` |
| Memory | 8 GB for the web console and scene generation; 16 GB or more with Gazebo or ArduPilot simulations |
| Cluster machines | Ubuntu, with k3s installed by [Machine Hub](#deploying-a-cluster), a separate tool; no source checkout |
| Development | Python 3.10 or newer (3.12 recommended) in `backend/env/`; Node.js 20.19 or newer for the frontend |

## Web console and workbench

The web console runs on the host with Worker node:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The workbench has no backend of its own: it uses the cluster selected in the console's left pane. That cluster's control-node-api serves the workbench gateway on its operator port (5174), and its worker nodes run the design space exploration, scene generation, trajectory generation, simulation and monitoring jobs. Deploy a cluster first (see [Deploying a cluster](#deploying-a-cluster)); without a selected cluster the workbench stays disconnected.

In the web console, under Workbench:

1. **Design Space Exploration**: give a specification (the metamodel and the well-formedness constraints, the first part of a FEC specification; the control node ships one) and a scope such as `TS = 2, StaticObstacle = 0`, and get every functional equivalence class (FEC) of it.
2. **Scene Generation**: load a functional scenario (one the exploration found, one of the control node's, or a `.problem` file) and generate a scene.
3. **Trajectory Generation**: the monitor-guided planner (a corridor seed with local repair), or straight trajectories over a time span.
4. **Simulation**: run the scenario and play it back in the encounter view (nautical canvas, a card per vessel pair, rule timeline) with the COLREGS monitor's outcomes. Every run is kept in Campaign History, which can replay it, and its frames can be exported.
5. **Connections**: the MQTT broker of live simulation sessions (the control node's own by default).

Under Cluster, **Domain Configuration** holds the COLREGS constants, vessel and obstacle types of the cluster, edited in a form generated from the YAML or as raw YAML and saved on the control node; every workbench run and campaign uses them. Every preset comes from the control node and ships in its image from `backend/assets/`: the domain presets (`domain_config/`), the functional scenarios (`generated_functional_models/all/`), the default specification of the design space exploration (`design_space/`) and the campaign presets the wizard starts from (`campaign_presets/`).

## Building images

`./build.sh` (a wrapper for [`deploy/scripts/build.sh`](deploy/scripts/build.sh)) builds the images and the release bundle Machine Hub deploys. It computes a fingerprint of each image's inputs, stores it in the image as the label `org.scenegems.fingerprint` and rebuilds only images whose label differs. The same commit gives the same fingerprints on Windows and Linux. The web console is not an image.

| Option | Builds |
|--------|--------|
| *(none)* or `--all` | every image |
| `-1`, `--backend` | `scenegems-control-node-api` and the five subsystem images |
| `-4`, `--arduagent` | `scenegems-arduagent` (the simulated vessels of an attended simulation with a real vessel, on a worker node) |
| `-5`, `--worker-node` | `scenegems-worker-node`, the worker node daemon |
| `--simulation` | `scenegems-gazebo-harmonic`, `scenegems-ardupilot-sitl`, `scenegems-mavproxy`, `scenegems-usv-navigation`, `scenegems-moos-ivp` |
| `--release <folder>` | everything a cluster runs, then the release bundle (see below) |
| `--fingerprints` | prints every image's fingerprint and builds nothing |
| `--no-check` | rebuilds the selected images even when their fingerprint matches |

Simulation images are needed only for Gazebo or ArduPilot runs. The first build of the Gazebo and SITL images compiles ArduPilot and the Gazebo plugins and takes a long time; later builds skip unchanged images.

The design space exploration image (`scenegems-design-space-exploration-subsystem`) holds the Refinery model generator and the subsystem's request service around it. The generator's source is not in this repository: the build fetches the commit of [fdominik98/refinery](https://github.com/fdominik98/refinery) that `REFINERY_COMMIT` in `deploy/images/upstream_pins.env` names and builds it with Gradle inside Docker (a few minutes the first time). To take a newer generator, change that pin and build again.

## Deploying a cluster

A cluster is one control node and any number of worker nodes, installed into one Kubernetes cluster from the release's Helm chart ([`deploy/kubernetes/chart/`](deploy/kubernetes/chart/)), in the namespace `scenegems`:

```text
 operator PC
   SceneGEMS checkout     ./build.sh --release <folder>: images, release.json, chart/
   Machine Hub            http://127.0.0.1:8080: machines, WireGuard mesh, Kubernetes clusters, releases
   web console            http://localhost:5173, reaches the operator API through a port forward
        |  cluster API (SSH forward to a fleet cluster, or the k3d cluster on the PC)
        v
 a Kubernetes cluster (k3s on the machines of the VPN 10.88.0.0/24, or k3d in Docker on the PC)
   control node   postgres (StatefulSet) | cluster-broker (plain MQTT, 1883) | control-node-api: worker node
            API (HTTP, 8443), operator API and workbench gateway (5174), scheduler, pipeline engine, artifact store
   worker nodes   one daemon Deployment per worker node, pinned to its Kubernetes node; it starts a Deployment
            per subsystem the worker node offers, and the simulation pool starts each run as a pod
```

A worker node runs at most one of each subsystem: design space exploration, scene generation, trajectory generation, monitoring and simulation, and only those its components need. Each is a service on the cluster's broker with a pool of tasks. The daemon leases a job from the control node and passes it to the subsystem as a request; the subsystem turns it into a task, queues it and runs it, as many at once as the worker node has slots for that kind of work. Every request carries a seed, so a job repeats exactly.

Every service is inside the cluster: the daemons reach the control node as `control-node-api` and the broker as `cluster-broker`, by name. Nothing is published on a host port. The operator API (5174) has no authentication and is reached only through a port forward from the PC (`kubectl port-forward service/control-node-api 5174:5174`).

SceneGEMS does not install machines, Kubernetes or a registry. Machine Hub, a separate repository, connects the machines in a WireGuard mesh, creates the Kubernetes cluster and installs a SceneGEMS release bundle into it. SceneGEMS defines in its release bundle what each role needs and how a member becomes chart values (`backend/src/scenegems_tool/cluster/release/roles.py`).

### Step by step with Machine Hub

1. **Prepare the machines and the cluster.** In Machine Hub, add the machines, check them and apply the VPN, then create a Kubernetes cluster on them (k3s: the server on one machine, agents on the others) or on the PC (k3d), with a registry in it.
2. **Build the release bundle** on the operator PC, from a clean checkout (`release.json` records the revision and flags uncommitted changes):

   ```bash
   ./build.sh --release ../scenegems-release
   ```

   This builds the images a cluster runs as `:latest`, pulls `postgres:16.10-alpine`, tags every SceneGEMS image of the release with the revision (`<commit>`, or `<commit>-dirty` from uncommitted changes) and writes the bundle. Each release names its own images. The bundle holds no source code:

   | File | Content |
   |------|---------|
   | `release.json` | format 2: revision, every image under its release tag with its ID and fingerprint, the chart (its folder, Helm release `scenegems`, namespace `scenegems`, the values every cluster gets) and the roles `control-node` and `worker-node` with their images, parameters, chart values, image values, the workloads that must be ready and the operator API's forward |
   | `chart/` | copy of `deploy/kubernetes/chart/` with a copy of `release.json`, which the chart puts into a ConfigMap |

3. **Add the members.** The cluster's name becomes the control node id: lowercase letters, digits and hyphens. Give one Kubernetes node the role `control-node` (its parameters: the browser origins the operator API allows, `http://localhost:5173,http://127.0.0.1:5173` by default, and the artifact limits) and any number of nodes the role `worker-node`. A worker node's name has at most 28 characters, since the names of its Deployments start with it. A worker node needs nothing from a deployed control node: the daemon dials `control-node-api` in the cluster and retries until it answers. Set two parameters per worker node member:
   - `SCENEGEMS_WORKER_NODE_COMPONENTS`: what the worker node runs, as a comma list. Vessel stack layers: `asv_system/replay`, `asv_system/usv_navigation`, `asv_system/moos_ivp`, `control_layer/none`, `control_layer/ardupilot` (SITL), `control_layer/custom`, `simulation_layer/kinematic`, `simulation_layer/ardupilot_sim`, `simulation_layer/gazebo` (Gazebo); subsystems: `design_space_exploration`, `scene_generation`, `trajectory_generation`, `monitoring`, `calibration`. The release lists the images of each component (a simulation layer adds the simulation subsystem's image) and Machine Hub pushes the images of the components chosen. The worker node starts the subsystem of every component it lists; any simulation layer, and `calibration`, start the simulation subsystem. A simulation runs on a worker node that has every layer of every vessel's stack: a kinematic replay needs `asv_system/replay,control_layer/none,simulation_layer/kinematic`, USV Navigation adds `asv_system/usv_navigation`, a SITL replay needs `asv_system/replay,control_layer/ardupilot,simulation_layer/ardupilot_sim`, a Gazebo replay the same with `simulation_layer/gazebo`, and the custom controller on Gazebo `asv_system/replay,control_layer/custom,simulation_layer/gazebo` (no SITL).
   - `SCENEGEMS_WORKER_NODE_SLOTS`: how many jobs of each type the worker node runs at once, which is the size of the task pool of the subsystem that runs them, as `type:slots`, for example `design_space_exploration:1,scene_generation:2,trajectory_generation:9,simulation:2,monitoring.post_hoc:2,calibration.deviation:1` on a 12-core machine (trajectory generation slots: cores minus 3). Job types: `design_space_exploration`, `scene_generation`, `trajectory_generation`, `simulation`, `monitoring.post_hoc`, `calibration.deviation`; each needs a component that serves it (a simulation layer for `simulation`, `monitoring` for `monitoring.post_hoc`, `calibration` for `calibration.deviation`). A design space exploration keeps every explored state in memory, so one slot per worker node is usually right. A simulation that is judged while it runs (monitor live) also needs the `monitoring` component and takes a `monitoring.post_hoc` slot for as long as it runs, so give a worker node that runs such campaigns as many monitoring slots as simulation slots, plus those for post hoc monitoring.

   The defaults make a kinematic worker node. Optional: labels that jobs can require (`key=value`) and the artifact cache bound.
4. **Deploy.** Machine Hub pushes the images the members need to the cluster's registry, builds one values file from the members by the rules in `roles.py` (the reference is `backend/src/tests/scenegems_tool/cluster/release/chart_values_builder.py`), installs the chart with `helm upgrade --install scenegems <bundle>/chart -n scenegems --create-namespace -f <values> --wait` and waits for the workloads the roles' `ready` names: `postgres`, `cluster-broker`, `control-node-api` (ready when its operator API answers `/health`) and `worker-node-<name>` per worker node. The chart's values schema refuses a values file the system cannot run (a worker node name of the wrong form, an unknown component or job type, a slot count below 1). There is no pairing, no certificate and no token: control node and worker nodes trust everything in the cluster. A worker node's id is its name, so keep worker node names unique within a cluster.
5. **Reach the operator API from the PC.** Machine Hub opens the release's forward (the role's `forwards`: the service `control-node-api`, port 5174). By hand, with the cluster's kubeconfig:

   ```bash
   kubectl --kubeconfig <cluster kubeconfig> -n scenegems port-forward service/control-node-api 5174:5174
   ```

   Check that every worker node is `online` and not out of date:

   ```bash
   curl http://127.0.0.1:5174/cluster/worker-nodes
   ```

6. **Open the web console** on the PC:

   ```bash
   cd frontend && npm install && npm run dev
   ```

   Open http://localhost:5173. The cluster selector in the left pane starts with "Local control node" at `http://127.0.0.1:5174`; add a cluster there for each port forward (one local port per control node, for example `... port-forward service/control-node-api 15174:5174` and `http://127.0.0.1:15174`). The page's origin must be one of the control node's allowed origins (the role's `SCENEGEMS_OPERATOR_ALLOWED_ORIGINS`). The **Cluster** section lists the worker nodes with their machine, components (out-of-date ones marked), slots in use and image state, and drains or resumes a worker node.
7. **Run a campaign.** In **Campaigns**, the wizard walks through scope (classes and folder patterns with quota and failure budget), domain constraints, trajectory generator, runs (vessel stack and monitor), resources and policy; the control node checks the config before you create the campaign paused or running. From the command line, in `backend/`:

   ```bash
   PYTHONPATH=src env/Scripts/python.exe -m scenegems_tool.assurance create <config.yaml> --start
   PYTHONPATH=src env/Scripts/python.exe -m scenegems_tool.assurance events <campaign id> --follow
   ```

   `--api` (or `SCENEGEMS_OPERATOR_URL`) chooses another control node; the default is `http://127.0.0.1:5174`. An example config is `backend/src/tests/scenegems_tool/assurance/campaign/data/exit_campaign.yaml`.
8. **Follow and inspect.** **Campaign History** lists campaigns and workbench entries; an entry shows the outputs of each step (open one in the workbench, or watch a running job live), and a campaign its coverage per class, events and controls (start, pause, drain, resume, stop). **Cluster** shows each worker node's pools (scene generation samples, trajectory search previews) and running jobs live, a simulation at a chosen speed. **Results** summarizes the monitor findings of an entry per executed step and lists the monitor summaries with filters, totals and CSV export, and a case's steps, run records and recorded run with the monitor's frames.

An attended run with Mission Planner gets a NodePort service per ground control port; its node port is in the job's status, and Mission Planner on the PC connects to `<node address>:<node port>`. On a k3d cluster only the node ports mapped when the cluster was created reach the PC.

### Updating and removing a cluster

- **New release**: commit, build a new bundle (`./build.sh --release <folder>`) and deploy it to the cluster (`helm upgrade` with the new chart and values). The database and the artifacts stay on their volume claims. A worker node whose image fingerprints differ from the control node's `release.json` gets no jobs until it runs the release's images. Fingerprints compare by image repository, not by tag: a worker node that has the same build under an older release's tag is up to date, and a campaign keeps its pinned fingerprints across releases. When `PROTOCOL_VERSION` (`backend/src/scenegems_tool/cluster/protocol/version.py`) changes, update the control node and all its worker nodes together; one install of the chart does both. A release that adds a component or a job type reaches a worker node only when the worker node's member lists it.
- **Remove**: `helm uninstall scenegems -n scenegems` removes the workloads, services, rights and the pools and runs the daemons started (they are owned by the daemons' Deployments). It keeps the Postgres volume claim (`data-postgres-0`), the artifact claim (`control-node-artifacts`) and the Secret `postgres` with the database password, so a later install of the same release name in the same namespace takes the database up again. Removing a cluster with its data means deleting those three as well, or the namespace. A worker node's runtime folder on its Kubernetes node (`/var/lib/scenegems/<name>`) stays too. Worker nodes need no re-pairing: they reconnect when a control node with the same id is back.

### Without Machine Hub: a cluster on this PC

[`deploy/kubernetes/scripts/local_cluster.sh`](deploy/kubernetes/scripts/local_cluster.sh) runs a whole cluster on the operator PC in k3d: a control node and one worker node on the k3d cluster's one node. It needs Docker, `k3d` (5.9.0 was used), `helm` (4.3.2) and `kubectl`, on the PATH or named by `SCENEGEMS_K3D`, `SCENEGEMS_HELM` and `SCENEGEMS_KUBECTL`:

```bash
./build.sh --release ../scenegems-release
deploy/kubernetes/scripts/local_cluster.sh up ../scenegems-release
deploy/kubernetes/scripts/local_cluster.sh forward
```

`up` creates the k3d cluster `scenegems-local` (API and node ports 30100 to 30119 on 127.0.0.1 only; the API server assigns node ports from that block, so an attended run's Mission Planner port is reachable), imports the release's images into it by tag, writes a values file (control node and worker node `local` pinned to the node; the worker node's components and slots are the role's defaults, or `SCENEGEMS_LOCAL_COMPONENTS` and `SCENEGEMS_LOCAL_SLOTS`) and installs the chart, waiting until everything is ready. `up` again with a newer bundle upgrades the release. `forward` keeps the operator API on `http://127.0.0.1:5174` (`SCENEGEMS_LOCAL_PORT` for another port) until Ctrl+C; add that URL as a cluster in the web console. `status` lists the workloads; `down` deletes the k3d cluster with everything in it. The kubeconfig and values file are in `~/.scenegems/local/<cluster>`. The tests marked `kubernetes` create their cluster the same way (`backend/src/tests/scenegems_tool/cluster/worker_node/k3d_cluster.py`) and deploy the chart as Machine Hub does (`backend/src/tests/scenegems_tool/assurance/local_cluster.py`).

A test keeps the chart, its values schema and the roles in `roles.py` in agreement (`backend/src/tests/scenegems_tool/cluster/release/test_stack_contract.py`, `test_chart_values.py`).

### Secrets

The control node's Postgres password is generated in the cluster by the chart on the first install, kept in the Secret `postgres` and reused on every upgrade; it never passes through a values file, the release or Machine Hub. There are no other secrets: the worker node API and the cluster broker are open to every pod of the cluster, which is trusted. A network policy keeps a simulation run's pod to the cluster broker, DNS and the ports of external brokers (`networkPolicy` in the chart's values).

### Ports

| Port | Where | Service |
|------|-------|---------|
| 5173 | operator PC | web console (Vite) |
| 5174 | operator PC, loopback, through the port forward | operator API and workbench gateway (service `control-node-api`) |
| 8443 | inside the cluster | worker node API over HTTP: control WebSocket, artifacts (service `control-node-api`) |
| 1883 | inside the cluster | cluster broker, plain anonymous MQTT (service `cluster-broker`) |
| 5432 | inside the cluster | Postgres (service `postgres`) |
| node ports | Kubernetes nodes | an attended run's ground control ports (Mission Planner); on k3d the mapped block, 30100 to 30119 by default |
| 8080 | operator PC, loopback | Machine Hub |
| 51820/udp | every machine | WireGuard |

## Development without Docker

### Backend

```bash
cd backend
python3.12 -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -e ".[dev]"          # Windows: pip install -e ".[dev,windows]"
```

Tests, from `backend/` (the default run skips tests marked `docker`, `kubernetes`, `postgres` or `slow`; select them with `-m`; the `kubernetes` tests create a k3d cluster of their own and need the images of `SCENEGEMS_TEST_IMAGE_TAG`, see `src/tests/scenegems_tool/cluster/worker_node/k3d_cluster.py`):

```bash
PYTHONPATH=src env/Scripts/python.exe -m pytest src/tests
```

Formatting and linting, line length 200: `black src/`, `python -m isort src/` and `flake8 -j 1 src/` (or `make format`, `make lint`, `make check`).

The research evaluation scripts (`evaluation_main.py`, `hyperparam_test.py`, `evaluate_hyperparameters.py`, `compress_eval_data.py`, `eval_vis.py`) are in `backend/src/scripts/`; see [`backend/README.md`](backend/README.md).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

| Command | Purpose |
|---------|---------|
| `npm run dev` | Vite dev server on port 5173 |
| `npm test` | vitest unit tests |
| `npm run lint` | ESLint |
| `npm run build` | production build, including the documentation |

The workbench connects to the gateway of the cluster selected in the left pane (`/ws/scenegems_backend_service` on its operator URL). See [`frontend/README.md`](frontend/README.md) and [`frontend/ARCHITECTURE.md`](frontend/ARCHITECTURE.md).

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| The web console loads but its WebSocket fails | select a cluster in the left pane and check that its control node answers at `<operator URL>/health` (the port forward is open) |
| Scene generation hangs | check under **Cluster** that a worker node offering `scene_generation` is online and not out of date |
| An attended simulation with Mission Planner or a real vessel finds no worker node | a worker node must list the stack's components (`asv_system/mission_planner`, or `asv_system/on_board`, `control_layer/real_vessel` and `simulation_layer/real_vessel`) in `SCENEGEMS_WORKER_NODE_COMPONENTS` and have their images |
| Gazebo GUI on Windows | an invalid `DISPLAY` falls back to headless (`deploy/images/gazebo/gazebo_entrypoint_prod.sh`); `GZ_HEADLESS=1` forces it |
| Old behavior after code changes | build a new release (`./build.sh --release <folder>`) and deploy it (Machine Hub, or `local_cluster.sh up <folder>`) |
| The port forward cannot bind 5174 | another program on this PC holds it; forward to another local port and add that URL in the console |
| A cluster section shows an unreachable control node or a CORS error | the port forward is closed (it also ends when the control node's pod is replaced: open it again), or the page's origin is not in `SCENEGEMS_OPERATOR_ALLOWED_ORIGINS` |
| A worker node gets no jobs | it is out of date: its images differ from the release; deploy the release to it |
| A subsystem pool of a worker node keeps restarting | `kubectl -n scenegems logs deployment/<worker node>-<subsystem>-subsystem`; its image may be older than the worker node's daemon: deploy one release for both |
| A worker node's daemon does not start | `kubectl -n scenegems logs deployment/worker-node-<name>`: the daemon names every variable it refuses |
| A simulation with the live monitor stays queued | no worker node with every layer of its stack also lists `monitoring` and has a free `monitoring.post_hoc` slot |

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for the full text.
