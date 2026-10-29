---
sidebar_position: 14
title: Data persistence
---

# Data persistence

The application stores user preferences and editor content in browser local storage so work survives page reloads:

- Active menu view (Scene Generation, Trajectory Generation, Simulation, Connections, or a Cluster section)
- Functional specification text
- Scene generation timeout setting
- Monitor configuration (scope, name, topic)
- Simulation vessel initialization drafts
- UI preferences (overlay toggles, panel visibility, split ratios, view mode)
- Per workbench page: its input (where it came from and, for inputs on the master, the reference) and the latest loaded entry

The domain configuration (COLREGS constants, vessel types, obstacle types) is not stored in the browser either: the master keeps it for the cluster, and an unsaved edit on the Domain Configuration page lasts until the page is reloaded. The contents of the loaded entries are not stored in the browser: after a reload each page fetches its entry from the master again, and a page whose entry was deleted is cleared. An input taken from a file is not kept across a reload. WebSocket connection state and trajectory buffers are *not* persisted: reload reconnects to the gateway and a live session needs its input loaded again.
