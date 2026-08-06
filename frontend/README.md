# SceneGEMS

A Scenario Generation and Execution Framework for Simulation-Based Assurance of Maritime Autonomous Surface Vehicles.

Browser-based console for exploring autonomous surface vehicle (ASV) maritime assurance scenarios: functional scenario specs (`.problem`), domain YAML configuration, 3D trajectory playback, COLREGS monitoring, and WARA-PS connection.

## Prerequisites

- Docker with Compose v2 (or `docker-compose`)
- For host-side Python work: Python 3.12+ (see [`backend/README.md`](../backend/README.md))

## Quick start (recommended)

From the **repository root**:

```bash
./start.sh
```

Open http://localhost:5173 (frontend starts before the backend). The WebSocket URL defaults to `ws://127.0.0.1:8000/ws/scenegems_backend_service` in `frontend/.env`.

## Quick start (frontend only, host Node)

```bash
npm install
cp .env.example .env
# Start the full stack from repo root with ./start.sh, or point VITE_WS_URL at a running backend
npm run dev
```

### Typical demo flow

1. Run `./start.sh` from the repo root (or ensure the backend is up and `VITE_WS_URL` in `.env` is correct).
2. Open **Domain Configuration**: presets load automatically from `public/domain_config/`.
3. Open **Scene Generation**: search functional presets, load one, click **Generate Initial Scene**.
4. **Initialize Scenario**, then open **Simulation** for dual-stream playback, metrics, and exports.
5. Optional: **Record & replay** in the right sidebar; **batch** multiple presets from Scene Generation.

## Documentation

User interface documentation is built with [Docusaurus](https://docusaurus.io/) and served at `/docs/`.

| Command | Description |
|---------|-------------|
| `npm run docs:dev` | Docusaurus dev server only (port 3000) |
| `npm run docs:pdf` | Export all UI docs to `website/static/scenegems-ui-documentation.pdf` |
| `npm run docs:build` | Generate PDF, then build static docs into `website/build/` |

During `npm run dev`, Docusaurus starts **only when you open** **Documentation** in the menu (or visit `/docs/`). The first visit may take a short moment while the docs dev server boots. Edit pages under `website/docs/`. Use **http://localhost:5173/docs/**.

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Vite + Docusaurus dev servers (app and `/docs/`) |
| `npm run build` | Build docs, regenerate preset manifest, typecheck, production build |
| `npm run presets:manifest` | Scan `public/generated_functional_models/` -> `presets-manifest.json` |
| `npm test` | Unit tests (Vitest) |
| `npm run lint` | ESLint |

## Configuration

| Variable | Purpose |
|----------|---------|
| `VITE_WS_URL` | WebSocket URL for the simulation backend (default in `.env.example`) |

## Static assets

- `public/domain_config/`: COLREGS constants, vessel types, obstacle types (YAML)
- `public/generated_functional_models/`: Functional scenario presets (`.problem`) and `presets-manifest.json`

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the domain/features layout and WebSocket message flow.
