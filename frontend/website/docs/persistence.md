---
sidebar_position: 14
title: Data persistence
---

# Data persistence

The application stores user preferences and editor content in browser local storage so work survives page reloads:

- Active menu view (Domain Configuration, Scene Generation, Simulation, WARA-PS)
- Domain YAML texts (COLREGS, vessel types, obstacle types)
- Functional specification text
- Scene generation timeout setting
- Monitor configuration (scope, name, topic)
- Simulation vessel initialization drafts
- UI preferences (overlay toggles, panel visibility, split ratios, view mode)

WebSocket connection state and trajectory buffers are *not* persisted: reload reconnects to the backend and requires re-initialization of scenarios as needed.
