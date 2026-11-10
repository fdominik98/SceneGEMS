---
sidebar_position: 14
title: Data persistence
---

# Data persistence

The application stores user preferences and editor content in browser local storage so work survives page reloads:

- Active menu view (Scene Generation, Trajectory Generation, Simulation, Connections, or a Cluster section)
- Color mode (light or dark)
- The known clusters and the active one
- FEC specification text
- The design space exploration page's specification, scope, maximum number of FECs and timeout
- Scene generation settings (timeout, low TCPA, live preview)
- Trajectory generation settings
- A fixed seed for the workbench's runs
- MQTT broker connection form
- Simulation vessel setup drafts, wind and waves
- UI preferences (layers and chart marks of the canvas, panel visibility, view mode, sections opened or closed)
- Per workbench page: its input (where it came from and, for inputs on the control node, the reference) and the latest loaded entry
- The campaign wizard's draft, and the filters and grouping of its catalogs
- Campaign History's open entry and step

The domain configuration (COLREGS constants, vessel types, obstacle types) is not stored in the browser: the control node keeps it for the cluster, and an unsaved edit on the Domain Configuration page lasts until the page is reloaded. The contents of the loaded entries are not stored in the browser either: after a reload each page fetches its entry from the control node again, and a page whose entry was deleted is cleared. An input taken from a file is not kept across a reload. WebSocket connection state and trajectory buffers are *not* persisted: reload reconnects to the gateway and a live session needs its input loaded again.
