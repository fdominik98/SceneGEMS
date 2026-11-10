---
sidebar_position: 2
title: Application layout
---

# Application layout

The interface is organized into persistent regions:

**Left pane**
: The navigation menu with the SceneGEMS brand, the hamburger toggle, the sections and their hints, the active cluster, the light or dark mode switch and the link to this documentation. Collapsed, it is a rail of icons with the names as tooltips. See [Left navigation menu](./navigation).

**Main area**
: The section chosen in the menu. A section of the Cluster group fills it with one page under a header. The workbench's Connections page does too, and its Design Space Exploration, Scene Generation, Trajectory Generation and Simulation pages divide it into the panes below.

**Center pane**
: On Design Space Exploration: the list of the FECs found, with the selected FEC's text. On the other three workbench pages: the [scene canvas](./scene-canvas), with the playback bar and the rule timeline under it on the trajectory and simulation pages.

**Right pane**
: On Design Space Exploration: the specification editor (the metamodel and the well-formedness constraints). On Scene Generation: the FEC specification editor and catalog, or the monitor preview. On Trajectory Generation and Simulation: the [monitoring panel](./monitoring), which a button in its toolbar hides and a button in the canvas toolbar shows again.

**Bottom panel**
: On the four workbench pages, under the canvas or the list: the step, its status, where the run happens and its run button, then the rows **Input**, **Setup** and **Result**. It takes the height it needs, at most half the page, until you [drag its resizer](./resizing).

**Global error bar**
: A dismissible alert at the bottom of the screen when scene generation or the workbench gateway reports an error. Click anywhere on the bar to dismiss.

Below 1100 px wide, the workbench's panes stack and scroll as one page. Below 800 px, the left pane becomes a bar at the top.
