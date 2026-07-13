---
sidebar_position: 4
title: Domain Configuration
---

# Domain Configuration

Domain Configuration defines the maritime domain model used by scene generation and the COLREGS monitor. Three YAML documents are edited in CodeMirror editors with syntax highlighting.

## Tabs

- **COLREGS constraints**: Rules and constants governing collision avoidance evaluation.
- **Vessel & obstacle types**: Split-pane editor for vessel type definitions and static obstacle types. A draggable divider adjusts column widths.

## Per-editor toolbar

Each YAML column provides:

| Action | Description |
|--------|-------------|
| Load preset… | Dropdown of bundled presets from `public/domain_config/` |
| Load file… | Import a local `.yaml` / `.yml` file |
| Export | Download the current editor content |

Default presets load automatically on first visit when fields are empty. Edited content is persisted in browser local storage.
