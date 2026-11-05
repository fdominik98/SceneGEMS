---
sidebar_position: 6
title: Simulation view
---

# Simulation view

The Simulation view is the primary operations console after a scenario is loaded. It consists of:

- **Scene canvas**: The encounter canvas or the nautical map (see [Scene canvas](./scene-canvas))
- **Playback bar and rule timeline**: under the canvas, for the preview and the simulation
- **Bottom control panel**: where the run happens and its setup (see [Control panel](./control-panel))
- **Right monitoring panel**: one stream at a time (Preview or Simulation): vessel pairs, frame data and charts (see [Monitoring panel](./monitoring))

When the monitoring panel is hidden, **Show monitoring panel** in the canvas toolbar restores it.

## Playback bar

Step back, play or pause, step forward, the time slider and the playback speed. Once a simulation has frames, **Live** follows the newest frame. Moving the slider leaves the newest frame; **Live** returns to it. The button at the end of the bar hides or shows the rule timeline.

## Rule timeline

A group of rows per vessel pair, for each stream: the encounter type over time and, when the group is opened, a row per rule with its result (failed, passed or not applicable yet) and a mark at the first failure. Clicking in the timeline moves the playhead there. A legend sits under it. The Trajectory Generation page has the same bar and timeline.

Switching to Simulation from another view triggers an automatic fit of the canvas to the current scenario.
