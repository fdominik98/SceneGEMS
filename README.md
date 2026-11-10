# SceneGEMS: Scenario Generation and Execution Framework for the Safety Assurance of Maritime Autonomous Surface Vehicles

SceneGEMS generates COLREGS encounter scenarios, simulates them with pluggable vessel stacks faster than real time and judges every run with a COLREGS monitor. The scene pipeline (functional, logical and concrete level) comes from the paper *Automated Generation of Functionally Complete Assurance Suites for COLREGS-Compliance of Autonomous Surface Vehicles*.

SceneGEMS runs on a cluster: one control node and any number of worker nodes, deployed by Machine Hub (the control node's machine can be your own PC). The web console works on the cluster selected in its left pane:

- **Workbench**: you explore the scenario classes of a specification, design a scenario, generate its scene and trajectories and simulate it interactively. The control node's control-node-api serves the workbench gateway and runs the live sessions; the jobs run on the cluster's worker nodes.
- **Campaigns**: every scenario class in a campaign's scope, or every class a design space exploration finds, is generated, simulated and monitored automatically; the web console configures, follows and inspects the campaigns.

## Repository layout

| Path | Content |
|------|---------|
| [`backend/`](backend/) | Python package roots under `backend/src/`: `scenegems_tool` (workbench gateway, subsystems, vessel stacks, the cluster's control node and worker node, the assurance pipeline, persistence), `functional_level`, `logical_level`, `concrete_level`, `evaluation`, `visualization`, `scripts`, `utils`, `tests`. Domain configuration, the 828 functional scenario classes and runtime assets are in `backend/assets/` |
| [`frontend/`](frontend/) | React and Vite web console with the sections Workbench, Cluster, Domain Configuration, Capabilities, Campaigns, Campaign History and Results; in-app documentation in `frontend/website/` |
| [`deploy/images/`](deploy/images/) | One folder per Docker image: `control_node_api`, `worker_node`, `mqtt_broker`, the subsystems `design_space_exploration`, `monitoring`, `scene_generation`, `scenario_execution`, `trajectory_generation`, the simulation images `gazebo`, `sitl`, `mavproxy`, `arduagent`, and `usv_navigation`, the image of the USV Navigation ASV software. `upstream_pins.env` pins the upstream sources of the Gazebo and SITL images and the Refinery commit and base images of the design space exploration image |
| [`deploy/control_node/`](deploy/control_node/), [`deploy/worker_node/`](deploy/worker_node/) | The compose file and `.env.example` of each cluster role |
| [`deploy/scripts/`](deploy/scripts/) | `build.sh` and its fingerprint and build helpers `docker-common.sh`; `./build.sh` in the repository root calls it |

The images that copy files from `backend/` (control-node-api, subsystems, worker node, Gazebo, SITL) build with the repository root as their Docker context, so their `COPY` lines start with `deploy/images/...` or `backend/...`.

## Requirements

| Requirement | Details |
|-------------|---------|
| Docker | Docker Engine with Compose v2 (`docker compose`) |
| Shell | Bash; on Windows Git Bash or WSL |
| Disk | Several GB for every image (Gazebo and SITL are the largest); less with `./build.sh --backend` |
| Memory | 8 GB for the web console and scene generation; 16 GB or more with Gazebo or ArduPilot simulations |
| Cluster machines | Ubuntu with Docker and Compose v2; no source checkout. They are prepared by [Machine Hub](#deploying-a-cluster), a separate tool |
| Development | Python 3.10 or newer (3.12 recommended) in `backend/env/`; Node.js 20.19 or newer for the frontend |

## Web console and workbench

The web console runs on the host with Worker node:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The workbench has no backend of its own: it uses the cluster selected in the console's left pane. That cluster's control-node-api serves the workbench gateway on its operator port (5174) and starts the live sessions on the control node's machine, and its worker nodes run the design space exploration, scene generation, trajectory generation, simulation and monitoring jobs. Deploy a cluster first (see [Deploying a cluster](#deploying-a-cluster)); without a selected cluster the workbench stays disconnected.

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
| `-4`, `--arduagent` | `scenegems-arduagent` (live sessions with ArduPilot, on the control node's machine) |
| `-5`, `--worker-node` | `scenegems-worker-node`, the worker node daemon |
| `--simulation` | `scenegems-gazebo-harmonic`, `scenegems-ardupilot-sitl`, `scenegems-mavproxy`, `scenegems-usv-navigation` |
| `--release <folder>` | everything a cluster runs, then the release bundle (see below) |
| `--fingerprints` | prints every image's fingerprint and builds nothing |
| `--no-check` | rebuilds the selected images even when their fingerprint matches |

Simulation images are needed only for Gazebo or ArduPilot runs. The first build of the Gazebo and SITL images compiles ArduPilot and the Gazebo plugins and takes a long time; later builds skip unchanged images.

The design space exploration image (`scenegems-design-space-exploration-subsystem`) is the Refinery model generator. Its source is not in this repository: the build fetches the commit of [fdominik98/refinery](https://github.com/fdominik98/refinery) that `REFINERY_COMMIT` in `deploy/images/upstream_pins.env` names and builds it with Gradle inside Docker (a few minutes the first time). To take a newer generator, change that pin and build again.

## Deploying a cluster

A cluster is one control node and any number of worker nodes:

```text
 operator PC
   SceneGEMS checkout     ./build.sh --release <folder>: images, release.json, stacks
   Machine Hub            http://127.0.0.1:8080: machines, WireGuard mesh, clusters
   web console            http://localhost:5173, reaches the control node over an SSH tunnel
        |  SSH
        v
 machines on the VPN 10.88.0.0/24
   control node   postgres | cluster-broker (plain MQTT, 1883) | control-node-api: worker node API (HTTP, 8443),
            operator API and workbench gateway (127.0.0.1:5174), scheduler, pipeline engine, artifact store
   worker nodes    worker node daemon, which starts a subsystem container per job or pool
```

SceneGEMS does not install machines or set up their network. Machine Hub, a separate repository, connects the machines in a WireGuard mesh and installs a SceneGEMS release bundle on the machines you give a role. SceneGEMS defines what each role needs in its release bundle and works with whichever machines are ready.

### Step by step with Machine Hub

1. **Prepare the machines.** Start Machine Hub on the operator PC (`.venv/Scripts/python -m machine_hub` in its folder, then http://127.0.0.1:8080) and set the SSH key path in Settings. The machines need Ubuntu, passwordless `sudo` for the SSH user, `python3`, and inbound UDP 51820 from each other. In Machine Hub:
   1. **Machines**: add the machines.
   2. **Scripts**: run `install-docker.sh` on new machines.
   3. **Machines, Check selected**: SSH, Docker, Compose and WireGuard must be fine on each machine.
   4. **VPN, Apply to machines**: every machine peers with every other on `10.88.0.0/24`. Add **Start hub** if the PC should join the mesh as `10.88.0.1`.
2. **Build the release bundle** on the operator PC, from a clean checkout (`release.json` records the revision and flags uncommitted changes):

   ```bash
   ./build.sh --release ../scenegems-release
   ```

   This builds the images a cluster runs as `:latest`, pulls `postgres:16.10-alpine`, tags every SceneGEMS image of the release with the revision (`<commit>`, or `<commit>-dirty` from uncommitted changes) and writes the bundle. Each release names its own images, so a machine can hold several releases, and the roles pass the tag to the machines as `SCENEGEMS_IMAGE_TAG`. The bundle holds no source code:

   | File | Content |
   |------|---------|
   | `release.json` | revision, every image under its release tag with its ID and fingerprint, and the roles `control-node` and `worker-node` with their images, fixed values, parameters, secrets, setup commands and outputs |
   | `stacks/control_node/docker-compose.yml` | copy of `deploy/control_node/docker-compose.yml` |
   | `stacks/control_node/docker-compose.live-sessions.yml` | copy of `deploy/control_node/docker-compose.live-sessions.yml`: the Docker socket for the workbench's live sessions |
   | `stacks/worker_node/docker-compose.yml` | copy of `deploy/worker_node/docker-compose.yml` |

3. **Create the cluster.** In **Clusters**, create a cluster from the bundle folder. Its name becomes the control node id: lowercase letters, digits and hyphens. It names the cluster's topics, containers and volumes.
4. **Add the control node.** Give one machine the role `control-node`. Its parameters have defaults: worker node API port 8443, broker port 1883, operator port 5174, Postgres port 5432, the browser origins the operator API allows (`http://localhost:5173,http://127.0.0.1:5173`), the artifact limits and `COMPOSE_FILE`. The control node's address is the machine's VPN address.

   `COMPOSE_FILE` (default `docker-compose.yml:docker-compose.live-sessions.yml`) chooses the compose files `docker compose up -d` reads. The live sessions file mounts the Docker socket into control-node-api, which the workbench's live sessions need (MQTT broker, real vessels, Mission Planner, ArduPilot live): they start their containers on the control node's machine, with that machine's locally built `:latest` images. Set it to `docker-compose.yml` for a control node without Docker access: the workbench then refuses live sessions with a clear error, the Connections page says that live sessions are off on this control node, and campaigns and cluster jobs work as before.
5. **Add the worker nodes.** Give any number of machines (the control node's machine too) the role `worker-node`. A worker node needs nothing from a deployed control node: it only needs the control node added to the cluster, because its `.env` gets the control node's VPN address and ports from it. Set two parameters per worker node member:
   - `SCENEGEMS_WORKER_NODE_COMPONENTS`: what the worker node runs, as a comma list. Vessel stack layers: `asv_software/replay`, `asv_software/usv_navigation`, `control_layer/none`, `control_layer/ardupilot` (SITL), `control_layer/custom`, `simulation_layer/kinematic`, `simulation_layer/ardupilot_sim`, `simulation_layer/gazebo` (Gazebo); subsystems: `design_space_exploration`, `scene_generation`, `trajectory_generation`, `monitoring`, `calibration`. The release lists the images of each component (a simulation layer adds the scenario execution runner) and Machine Hub installs the images of the components chosen. A simulation runs on a worker node that has every layer of every vessel's stack: a kinematic replay needs `asv_software/replay,control_layer/none,simulation_layer/kinematic`, USV Navigation adds `asv_software/usv_navigation`, a SITL replay needs `asv_software/replay,control_layer/ardupilot,simulation_layer/ardupilot_sim`, a Gazebo replay the same with `simulation_layer/gazebo`, and the custom controller on Gazebo `asv_software/replay,control_layer/custom,simulation_layer/gazebo` (no SITL).
   - `SCENEGEMS_WORKER_NODE_SLOTS`: how many jobs of each type the worker node runs at once, as `type:slots`, for example `design_space_exploration:1,scene_generation:2,trajectory_generation:9,simulation:2,monitoring.post_hoc:2,calibration.deviation:1` on a 12-core machine (trajectory generation slots: cores minus 3). Job types: `design_space_exploration`, `scene_generation`, `trajectory_generation`, `simulation`, `monitoring.post_hoc`, `calibration.deviation`; each needs a component that serves it (a simulation layer for `simulation`, `monitoring` for `monitoring.post_hoc`, `calibration` for `calibration.deviation`). A design space exploration keeps every explored state in memory, so one slot per worker node is usually right.

   The defaults make a kinematic worker node. A worker node refuses `SCENEGEMS_WORKER_NODE_CAPABILITIES` and the job types `simulation.kinematic`, `simulation.ardupilot_sim` and `simulation.gazebo` of earlier releases with a message naming their replacements, so Machine Hub members that set them need the two parameters above. Optional: labels that jobs can require (`key=value`) and the artifact cache bound.
6. **Deploy all.** Machine Hub deploys every member; a worker node does not wait for the control node, since it keeps retrying its connection. For each member it:
   1. loads the role's images from the PC, skipping images the machine already has; an image the machine has under another tag (the same image ID, or the same fingerprint label) is only tagged with the release's name;
   2. copies the role's compose file and `release.json` to `~/machine_hub/stacks/<project>/` on the machine;
   3. writes `.env` with mode 600: the role's fixed values, your parameters and the secrets. The control node's Postgres password is generated on the machine once and kept on later deploys;
   4. runs the role's setup commands (none in this release);
   5. runs `docker compose up -d` and waits until the role's services are ready.

   There is no pairing, no certificate and no token: control node and worker nodes trust everything on the VPN. A worker node's id is its name, so keep worker node names unique within a cluster.
7. **Reach the control node from the PC.** The operator API has no authentication, so the control node publishes it on its loopback address only. Open an SSH tunnel and keep it open while you use the web console or the command line:

   ```bash
   ssh -L 5174:127.0.0.1:5174 <user>@<control node address>
   ```

   Check that every worker node is `online` and not out of date:

   ```bash
   curl http://127.0.0.1:5174/cluster/worker-nodes
   ```

8. **Open the web console** on the PC:

   ```bash
   cd frontend && npm install && npm run dev
   ```

   Open http://localhost:5173. The cluster selector in the left pane starts with "Local control node" at `http://127.0.0.1:5174`; add a cluster there for each tunnel (one local port per control node, for example `ssh -L 15174:127.0.0.1:5174 ...` and `http://127.0.0.1:15174`). The page's origin must be one of the control node's allowed origins (`SCENEGEMS_OPERATOR_ALLOWED_ORIGINS`). The **Cluster** section lists the worker nodes with their machine, components (out-of-date ones marked), slots in use and image state, and drains or resumes a worker node.
9. **Run a campaign.** In **Campaigns**, the wizard walks through scope (classes and folder patterns with quota and failure budget), domain constraints, trajectory generator, runs (vessel stack and monitor), resources and policy; the control node checks the config before you create the campaign paused or running. From the command line, in `backend/`:

   ```bash
   PYTHONPATH=src env/Scripts/python.exe -m scenegems_tool.assurance create <config.yaml> --start
   PYTHONPATH=src env/Scripts/python.exe -m scenegems_tool.assurance events <campaign id> --follow
   ```

   `--api` (or `SCENEGEMS_OPERATOR_URL`) chooses another control node; the default is `http://127.0.0.1:5174`. An example config is `backend/src/tests/scenegems_tool/assurance/campaign/data/exit_campaign.yaml`.
10. **Follow and inspect.** **Campaign History** lists campaigns and workbench entries; an entry shows the outputs of each step (open one in the workbench, or watch a running job live), and a campaign its coverage per class, events and controls (start, pause, drain, resume, stop). **Cluster** shows each worker node's pools (scene generation samples, trajectory search previews) and running jobs live, a simulation at a chosen speed. **Results** summarizes the monitor findings of an entry per executed step and lists the monitor summaries with filters, totals and CSV export, and a case's steps, run records and recorded run with the monitor's frames.

### Updating and removing a cluster

- **New release**: commit, build a new bundle (`./build.sh --release <folder>`), choose it for the cluster in Machine Hub and press **Deploy all**. The database stays. A worker node whose image fingerprints differ from the control node's `release.json` gets no jobs until it runs the release's images. Fingerprints compare by image repository, not by tag: a worker node that has the same build under an older release's tag is up to date, and a campaign keeps its pinned fingerprints across releases. When `PROTOCOL_VERSION` (`backend/src/scenegems_tool/cluster/protocol/version.py`) changes, update the control node and all its worker nodes together. A release that adds a component or a job type (the design space exploration came with protocol 7) reaches a worker node only when the worker node's member lists it: add `design_space_exploration` to its `SCENEGEMS_WORKER_NODE_COMPONENTS` and `design_space_exploration:1` to its `SCENEGEMS_WORKER_NODE_SLOTS` in Machine Hub before **Deploy all**.
- **Remove**: Machine Hub's Remove stops a member's stack and deletes its volumes and folder. For a control node that deletes its database. Worker nodes need no re-pairing: they reconnect when a control node with the same id is back.

### Without Machine Hub

The same steps by hand, which is also what the single-host rehearsal test (`backend/src/tests/scenegems_tool/assurance/local_cluster.py`) does:

1. Copy the images of each role in `release.json` to its machine under the names `release.json` lists (the release's tag), for example `docker save <images> | ssh <user>@<machine> docker load`. The control node needs `scenegems-control-node-api`, `scenegems-mqtt-broker` and `postgres:16.10-alpine`; a worker node needs `scenegems-worker-node` and the images of each component it offers (the role's `SCENEGEMS_WORKER_NODE_COMPONENTS` items in `release.json`: `scenegems-scene-generation-subsystem`, `scenegems-trajectory-generation-subsystem`, `scenegems-scenario-execution-subsystem` for the simulation layers, `asv_software/replay`, `control_layer/custom` and calibration, `scenegems-monitoring-subsystem`, plus `scenegems-usv-navigation` for `asv_software/usv_navigation`, `scenegems-ardupilot-sitl` for `control_layer/ardupilot` and `scenegems-gazebo-harmonic` for `simulation_layer/gazebo`).
2. On the control node, in a folder of its own with both files of `stacks/control_node/` and `release.json`: write `.env` from [`deploy/control_node/.env.example`](deploy/control_node/.env.example) (control node id, project name, the release's `SCENEGEMS_IMAGE_TAG`, `COMPOSE_FILE`, a generated Postgres password), `chmod 600 .env`, then:

   ```bash
   docker compose up -d
   ```

3. On each worker node, in a folder of its own with `stacks/worker_node/docker-compose.yml`: write `.env` from [`deploy/worker_node/.env.example`](deploy/worker_node/.env.example) with the control node's URL and id, the worker node name, its components and slots, the release revision and the release's `SCENEGEMS_IMAGE_TAG`, then `docker compose up -d`. This works before or after the control node is up.

A test keeps the roles in `backend/src/scenegems_tool/cluster/release/roles.py`, the compose files and both `.env.example` files in agreement.

### Secrets

Real `.env` files are gitignored and stay on the machines. The control node's Postgres password is generated on the control node. There are no other secrets: the worker node API and the cluster broker are open to every machine on the VPN, which is trusted. Do not publish them beyond it.

### Ports

| Port | Where | Service |
|------|-------|---------|
| 5173 | operator PC | web console (Vite) |
| 5174 | control node loopback | operator API and workbench gateway |
| 8443 | control node | worker node API over HTTP: control WebSocket, artifacts |
| 1883 | control node | cluster broker, plain anonymous MQTT |
| 5432 | control node loopback | Postgres |
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

Tests, from `backend/` (the default run skips tests marked `docker`, `postgres` or `slow`; select them with `-m`):

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
| The web console loads but its WebSocket fails | select a cluster in the left pane and check that its control node answers at `<operator URL>/health` (the tunnel is open) |
| Scene generation hangs | check under **Cluster** that a worker node offering `scene_generation` is online and not out of date |
| Gazebo or ArduPilot live sessions fail | the control node's machine needs `./build.sh --simulation` and `--arduagent` images, and control-node-api the Docker socket (`docker-compose.live-sessions.yml` in `COMPOSE_FILE`) |
| Gazebo GUI on Windows | an invalid `DISPLAY` falls back to headless (`deploy/images/gazebo/gazebo_entrypoint_prod.sh`); `GZ_HEADLESS=1` forces it |
| Old behavior after code changes | build a new release (`./build.sh --release <folder>`) and deploy it with Machine Hub |
| The tunnel cannot bind 5174 | a control node on this PC already publishes it; tunnel to another local port |
| A cluster section shows an unreachable control node or a CORS error | the tunnel is closed, or the page's origin is not in `SCENEGEMS_OPERATOR_ALLOWED_ORIGINS` |
| A worker node gets no jobs | it is out of date: its images differ from the release; deploy the release to it |

## License

This project is licensed under the MIT License. See [`LICENSE`](LICENSE) for the full text.
