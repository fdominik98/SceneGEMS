# SceneGEMS

A Scenario Generation and Execution Framework for Simulation-Based Assurance of Maritime Autonomous Surface Vehicles.

Browser-based console for exploring autonomous surface vehicle (ASV) maritime assurance scenarios: functional scenario specs (`.problem`), domain YAML configuration, trajectory playback, COLREGS monitoring, and jobs on a SceneGEMS cluster.

## Prerequisites

- Node.js 20.19 or newer
- A deployed SceneGEMS cluster whose master's operator API this machine reaches (see the repository [`README.md`](../README.md))

## Quick start

```bash
npm install
npm run dev
```

Open http://localhost:5173. The console has no backend of its own: the workbench connects to the gateway of the cluster selected in the left pane (`/ws/scenegems_backend_service` on the master's operator URL), and the cluster's nodes run its jobs.

### Typical demo flow

1. Run `npm run dev` and select a deployed cluster in the left pane.
2. Optional: open **Domain Configuration** in the Cluster group to review the cluster's COLREGS constants, vessel types and obstacle types (the master's default presets apply until one is saved).
3. Open **Scene Generation**: pick one of the master's functional scenarios (use **Find a preset** to search and filter), then click **Generate scene**.
4. Click **Next: Trajectory Generation**, generate trajectories, then **Load for Simulation** to open **Simulation** for dual-stream playback, metrics, and exports.
5. Optional: **Record and replay** under Simulation controls, and the **Batch** tab in Scene Generation to run several functional scenarios.

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
| `npm run build` | Build docs, typecheck, production build |
| `npm test` | Unit tests (Vitest) |
| `npm run lint` | ESLint |

## Presets

The console ships no presets of its own. The domain presets, the functional scenarios and the campaign presets come from the active cluster's master (`backend/assets/` in the master image): see the catalog and setting routes in `domain/cluster/presetsApi.ts`.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the domain/features layout and WebSocket message flow.
