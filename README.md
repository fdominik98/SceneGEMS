# SceneGEMS: Scenario Generation and Execution Framework for the Safety Assurance of Maritime Autonomous Surface Vehicles

Monorepo for automated COLREGS scene generation, simulation orchestration, and the SceneGEMS web console. The Python backend implements the three-level scene pipeline (functional -> logical -> concrete) from the research paper *Automated Generation of Functionally Complete Assurance Suites for COLREGS-Compliance of Autonomous Surface Vehicles*.

## Components

| Component | Path | Description |
|-----------|------|-------------|
| **Backend** | [`backend/`](backend/) | Python WebSocket service, scene generation, simulation orchestration |
| **Frontend** | [`frontend/`](frontend/) | React/Vite UI for scenario exploration and playback |
| **MQTT broker** | [`mqtt_broker/`](mqtt_broker/) | NanoMQ image used by the main compose stack |
| **Simulation images** | `gazebo/`, `sitl/`, `mavproxy/`, `arduagent/` | Gazebo Harmonic + ArduPilot SITL Docker images |
| **Subsystems** | `monitoring/`, `scenario_generation/`, `scenario_execution/` | Containerized worker images spawned by the backend |

## Prerequisites

- **Docker** with Compose v2 (`docker compose`) or legacy `docker-compose`
- **Docker socket access**: the backend mounts `/var/run/docker.sock` to spawn subsystem and simulation containers
- **Git Bash or WSL** on Windows (the root scripts are Bash)
- **Disk space**: a full image build (Gazebo, SITL, subsystems) can take several GB

Optional for host-side development (without Docker):

- Python **3.12** (≥ 3.10 supported)
- Node.js **18+** and npm (frontend)

## Quick start (Docker)

From the repository root:

```bash
# 1. Build images (skips unchanged images via fingerprint stamps)
./build.sh

# 2. Start frontend, MQTT broker, and backend
./start.sh
```

Open:

| Service | URL |
|---------|-----|
| **Web UI** | http://localhost:5173 |
| **Backend health** | http://localhost:8000/health |
| **MQTT (host)** | `localhost:1882` (maps to broker port 1883 inside compose) |

Press **Ctrl+C** while `start.sh` is tailing backend logs to stop the stack. Shutdown also tears down subsystem containers (monitoring, scenario generation, scenario execution) started during the session.

> **Note:** `start.sh` does not build images. If you see `Missing image … Run ./build.sh first`, run `./build.sh` (or a targeted build; see below).

## Building images

[`build.sh`](build.sh) rebuilds only when inputs change (fingerprints stored under `.docker-stamps/`). Use `--no-check` to force a rebuild.

```bash
./build.sh --help
```

| Flag | What it builds |
|------|----------------|
| *(no args)* or `--all` | Every image, including MQTT broker |
| `-1`, `--backend` | `scenegems-backend`, monitor, scenario-generation, scenario-execution subsystems |
| `-2`, `--frontend` | `scenegems-frontend:dev` |
| `-3`, `--stack` | Backend + frontend (no simulation images) |
| `-4`, `--arduagent` | `scenegems-arduagent:latest` |
| `--simulation` | `scenegems-gazebo-harmonic`, `scenegems-ardupilot-sitl`, `scenegems-mavproxy` |
| `--no-check` | Skip stale checks; always `docker build` (with no other flags: same targets as `--all`) |

**Examples:**

```bash
# After Python/backend changes only
./build.sh --backend

# After UI changes only
./build.sh --frontend

# App stack without Gazebo/SITL (scene generation + UI, no live Gazebo sim)
./build.sh --stack

# Full stack including simulation runtime (needed for Gazebo/ArduPilot execution)
./build.sh --all

# Force rebuild everything (same as ./build.sh --no-check)
./build.sh --all --no-check

# Force rebuild app stack only (backend + frontend, skip Gazebo/SITL)
./build.sh --stack --no-check
```

Simulation images are **not** required to run the web console, scene generation, or trajectory preview. Build them when you use **Simulation** with Gazebo or ArduPilot agents.

## Using the web console

Typical workflow after `./start.sh`:

1. Open http://localhost:5173
2. **Domain Configuration**: presets load from `frontend/public/domain_config/` (COLREGS constants, vessel types, obstacles).
3. **Scene Generation**: search functional presets (`.problem` files), load one, click **Generate Initial Scene**.
4. **Initialize Scenario**: loads the scene and streams preview trajectory chunks over WebSocket.
5. **Simulation**: configure agents, wind/waves, and run dual-stream playback with COLREGS metrics and exports.

**Tips:**

- Load a full evaluation JSON (with `trajectories.scene_list`) and use **Initialize Scenario** to stream the complete preview trajectory, not only `best_scene`.
- **Record & replay** and batch generation are available from the right sidebar and Scene Generation pane.
- In-app documentation: open **Documentation** in the menu (or visit http://localhost:5173/docs/). Docusaurus starts on first visit.

## Architecture overview

```text
Browser (frontend :5173)
    │  WebSocket  ws://127.0.0.1:8000/ws/scenegems_backend_service
    ▼
Backend (scenegems-backend :8000)
    │  MQTT  broker:1883
    ├── scenegems-scenario-generation-subsystem   (scene generation workers)
    ├── scenegems-monitoring-subsystem               (COLREGS monitoring)
    └── scenegems-scenario-execution-subsystem    (Gazebo / SITL / arduagent per scenario)
```

Runtime-generated assets (SDF models, compose files, trajectories) are stored in the Docker named volume **`scenegems_runtime_assets`**, shared between the backend and subsystem containers.

## Development without Docker

### Backend (Python)

```bash
cd backend
python3.12 -m venv env
source env/bin/activate          # Windows: env\Scripts\activate
pip install -e .                 # Windows: pip install -e ".[windows]"
```

Linting and formatting (from `backend/`):

```bash
make lint      # flake8 src/
make format    # black + isort
make check     # lint + format + mypy
```

Run the WebSocket server locally (requires MQTT broker and subsystem images if you exercise simulation):

```bash
cd backend
source env/bin/activate
PYTHONPATH=src uvicorn scenegems_tool.backend_service.websocket_app:app --host 0.0.0.0 --port 8000
```

See [`backend/README.md`](backend/README.md) for the research evaluation scripts (`evaluation_main.py`, `hyperparam_test.py`, `eval_vis.py`, etc.).

### Frontend (Node)

```bash
cd frontend
npm install
cp .env.example .env
# Ensure the backend is running; default VITE_WS_URL points at localhost:8000
npm run dev
```

| Command | Purpose |
|---------|---------|
| `npm run dev` | Vite dev server on port 5173 |
| `npm run build` | Production build (includes docs staging) |
| `npm test` | Vitest unit tests |
| `npm run lint` | ESLint |

See [`frontend/README.md`](frontend/README.md) and [`frontend/ARCHITECTURE.md`](frontend/ARCHITECTURE.md) for UI structure and WebSocket message flow.

Subsystem containers (monitoring, scenario generation, scenario execution) run from pre-built images only. After backend or subsystem code changes, rebuild with `./build.sh --backend` (or the relevant target) before restarting the stack.

## Research and batch evaluation

The original MSR/DC evaluation pipeline lives under `backend/src/scripts/`. Run from `backend/` with the virtual environment active:

```bash
python src/scripts/evaluation_main.py      # Main scene-generation evaluation
python src/scripts/hyperparam_test.py      # Hyperparameter tuning
python src/scripts/evaluate_hyperparameters.py
python src/scripts/compress_eval_data.py   # Compress results for plotting
python src/scripts/eval_vis.py           # Generate evaluation figures
python src/scripts/table_browser.py        # Dash table browser for eval data
```

Large measurement datasets are not shipped in the repo; see [`backend/README.md`](backend/README.md) for supplementary data notes.

## Configuration reference

### Main compose stack ([`docker-compose.yml`](docker-compose.yml))

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_WS_URL` | `ws://127.0.0.1:8000/ws/scenegems_backend_service` | Frontend → backend WebSocket (set in frontend service env) |
| `MQTT_BROKER_HOST` | `broker` | Backend MQTT hostname inside compose |
| `SCENEGEMS_DOCKER_NETWORK` | `scenegems_default` | Network attached to spawned subsystem containers |
| `SCENEGEMS_RUNTIME_VOLUME` | `scenegems_runtime_assets` | Named volume for generated simulation assets |

### Ports

| Port | Service |
|------|---------|
| 5173 | Frontend (Vite) |
| 8000 | Backend HTTP + WebSocket |
| 1882 | MQTT (host → broker 1883) |
| 8082 | MQTT WebSocket (host → broker 8083) |

## Troubleshooting

| Symptom | What to try |
|---------|-------------|
| `Missing image … Run ./build.sh first` | Run `./build.sh` or `./build.sh --stack` before `./start.sh` |
| UI loads but WebSocket fails | Confirm backend is up at http://localhost:8000/health; check `VITE_WS_URL` in `frontend/.env` |
| Scene generation hangs | Ensure `scenegems-scenario-generation-subsystem` image exists (`./build.sh --backend`); inspect `docker logs scenegems_backend` |
| Simulation / Gazebo errors | Run `./build.sh --simulation` (and `--arduagent` if using ArduPilot agents); backend needs Docker socket access |
| Stale behavior after code changes | `./build.sh --backend --no-check` (or relevant target with `--no-check`) |
| Windows Gazebo GUI issues | Invalid `DISPLAY` falls back to headless in `gazebo/entrypoint.sh`; use `GZ_HEADLESS=1` for server-only mode |

## Further reading

- [`backend/README.md`](backend/README.md): Python setup, project structure, evaluation scripts
- [`frontend/README.md`](frontend/README.md): UI scripts, docs, static assets
- [`frontend/ARCHITECTURE.md`](frontend/ARCHITECTURE.md): Frontend domain layout and protocol
