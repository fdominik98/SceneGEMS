---
sidebar_position: 7
title: Campaign wizard
---

# Campaign wizard

The Campaigns section defines and starts campaigns. A campaign runs a consecutive part of the chain design space exploration, scene generation, trajectory generation and simulation, with an optional monitor after each step. The wizard walks through the choices and checks the finished config on the control node before it creates the campaign. Your entries are kept in this browser until the campaign is created or you discard them.

## Presets

Above the pages, **Start from a preset** opens the catalog of the campaign presets of the active cluster's control node: the ones its image ships for campaign runs that come up again and again (`backend/assets/campaign_presets/`), and the ones saved on the cluster. Each card says what the preset selects and runs: its vessel and obstacle counts, its FECs and cases, its simulation stacks and its steps.

Find a preset with the search box, or with the filters:

| Filter | What it looks at |
|--------|------------------|
| Source | Shipped with the control node, or saved on this cluster |
| Vessels | The vessel counts of the FECs in the preset's scope. **Set by the input** is a preset without a scope: the input you pick in the wizard decides |
| Obstacles | The obstacle counts of those FECs, or **Set by the input** |
| Simulation stack | The stacks of the preset's runs |
| Steps | The steps the preset runs; with several ticked it needs to run all of them |

Ticking several values of a filter shows the presets with any of them (Steps and the stack catalog's Supports need all of them), and different filters narrow together. The number beside a value says how many presets you would see with it. A filter that would not tell the presets apart is left out. **Group by** sorts the cards by source, vessels, simulation stack or steps; a preset with several values, such as two stacks, shows under each of them. The filters and the grouping are kept in this browser.

**Load into the wizard** replaces the draft with the preset (the wizard asks first when the draft has entries) and opens the Steps page, so you only adjust what differs. A card warns when a run of the preset needs a stack this control node cannot run.

| Shipped preset | What it runs |
|----------------|--------------|
| Smoke test: one case per two-vessel FEC | The whole chain once per two-vessel FEC without obstacles, kinematic replay: the check after a deployment |
| Two-vessel encounters on the kinematic layer | Five cases of each two-vessel FEC, with and without an obstacle |
| Three-vessel encounters on the kinematic layer | Three cases of each three-vessel FEC |
| Four-vessel encounters on the kinematic layer | One case of each four-vessel FEC, with longer timeouts |
| USV Navigation against the planned trajectories | Two runs per case: the planned trajectories replayed, and USV Navigation steering the own ship |
| ArduPilot SITL replay of two-vessel encounters | The planned trajectories replayed on ArduPilot SITL |
| ArduPilot SITL repeatability: three repeats per case | Three SITL repeats per case, so calibration measures their deviation |
| Gazebo replay of two-vessel encounters | The planned trajectories replayed on SITL against a Gazebo world |
| Scene generation over the whole catalog | One scene per functional scenario, judged as a single scene |
| Trajectory planning check without simulation | Scene and trajectory generation with the planned trajectories judged |
| Simulate saved trajectories: kinematic and ArduPilot SITL | Simulation only; pick the trajectories on the Input page |
| USV Navigation on straight trajectories with low TCPA | One case per two-vessel FEC without obstacles, low TCPA enforced and straight trajectories, USV Navigation steering the own ship, with the post hoc monitor after every step |
| Design space exploration: every three-vessel FEC, one case each | Explores `TS = 2, StaticObstacle = 0` with the control node's default specification, then scene generation, trajectory generation and a kinematic replay with the post hoc monitor, one case of each FEC found |

**Save this draft as a preset** stores the current draft on the control node under a name, with a description; tick **Replace a saved preset of the same name** to overwrite one. A preset keeps the steps, scope, domain, trajectories, runs, resources and policy, but no input: uploaded files and picked outputs belong to one campaign, so you pick them again each time. A saved preset can be deleted; the shipped ones cannot.

## Campaign map

Above the pages, the campaign map draws the campaign as a graph of what it does, as set so far. The chain runs left to right: the input, each step the campaign runs, one box per simulation run inside the simulation frame (every case goes through each run), and the review. Arrows show what each part hands on. A step the campaign does not run is a dashed box marked "Not run". Under the chain, a row holds what applies to the whole campaign: Steps, Domain, Resources and Policy.

Each box says in a few words what its page holds (the FECs and cases of the input, a step's monitor, a run's stack and repeats, whether the control node accepted the config), so you see what the earlier pages set while you fill in the next one. A box opens its page; a run's box opens the Simulation page at that run. The boxes of the page shown are highlighted, and a red count marks the problems a page has. In a window too narrow for the whole map, it moves to the page you are on and shades the side that goes on; drag it sideways to see the rest.

**List** shows the pages as a numbered list in place of the map, and **Map** brings the map back. The choice is kept in this browser. The footer says which page of how many you are on.

## Explanations

The pages show their fields with little text by default: a field's explanation appears while you edit it, and of a set of options only the chosen one explains itself. Tick **Show explanations** above the map to see every explanation and the notes about each page. The choice is kept in this browser.

## Pages

The wizard shows only the pages the chosen steps need. Each step the campaign runs has a page of its own with its settings and the monitor after it.

| Page | Shown when | What it holds |
|------|------------|---------------|
| Steps | always | The campaign's name and description, the first and the last step |
| Input | always | What the first step starts from: catalog FECs and scenario files, scenes, or trajectories. A campaign that starts with the exploration takes none: its FECs come from the exploration |
| Domain | always | The cluster's domain configuration, or customized COLREGS constants, vessel types and obstacle types for this campaign only |
| Design space exploration | design space exploration is a step | The specification, the scope, the maximum number of FECs, the timeout and, when later steps run, the cases and the failure budget of each explored FEC |
| Scene generation | scene generation is a step | The monitor after scene generation, the scene generation timeout and the low TCPA option |
| Trajectory generation | trajectory generation is a step | The trajectory generator and its parameters, and the monitor after trajectory generation |
| Simulation | simulation is a step | The simulation runs: stack (the kinematic layer, ArduPilot on SITL or Gazebo, or the custom controller on Gazebo, each with replay or USV Navigation on the own ship), environment, seed, repeats and monitor |
| Resources | always | The machines the campaign may use, with the needs of the chosen steps checked against them. Only the queues of the steps that run are listed |
| Policy | always | Retention, frames, the base seed and stop conditions |
| Review | always | The generated YAML (config format 3, which lists a scope entry's FECs under `fecs`), the control node's check of it and the buttons that create the campaign |

A run's **Stack** field opens the catalog of the control node's stacks, with the same search, filters and grouping as the presets. It filters by simulation layer, control layer, own ship software, repeatability and what a run on the stack supports (wind, waves, early stop). A stack the control node cannot run stays listed with the reason, but cannot be picked. Picking another stack clears the values that belonged to the old one; picking the same stack again changes nothing.

## Steps

Choose **Start with** and **Stop after**. The steps in between run too, so the part is always consecutive: the design space exploration alone or with any steps after it, scene generation alone, scene generation and trajectory generation, scene generation through simulation, trajectory generation alone or with simulation, or simulation alone. A step that is not chosen hides its pages and writes nothing into the config.

The monitor after each step is chosen on the step's own page:

| Step | Monitor choice |
|------|----------------|
| Design space exploration | None: it has no monitor |
| Scene generation | No monitor, or the post hoc monitor, which judges each generated scene as a one-scene log (the initial situation) |
| Trajectory generation | No monitor, or the post hoc monitor, which judges the planned trajectories |
| Simulation | Set per run on the Simulation page: post hoc, live or none |

Changing the first step removes chosen input items that do not fit it, such as scenes when the campaign now starts with simulation.

## Design space exploration

This page is shown when the design space exploration is a step. It holds:

- **Metamodel and well-formedness constraints**: the specification editor, with **Load the default**, **Open file...** and an export, as on the [Design Space Exploration](./design-space-exploration) page. An empty editor starts from the control node's default, and a preset that leaves the specification out explores that default. Its **Text** and **Graph** switch shows the specification as a [metamodel graph](./design-space-exploration#text-or-graph); the choice is the same as on the workbench page.
- **Scope**: how many objects of each class a model has, such as `TS = 2, StaticObstacle = 0`, checked as you type.
- **Max FECs**: the search stops after this many; empty finds every FEC. **Timeout**: how long the search may run; the FECs found until then are kept.
- **Cases per explored FEC** and **Failure budget per explored FEC**: shown when a step follows the exploration. They are the quota and the failure budget that every FEC the exploration finds gets (see [Quota and failure budget](#quota-and-failure-budget)). Without a later step the page says that the campaign runs the exploration alone, so its FECs need no cases.

How many FECs there are is known only once the exploration ran. The review therefore says "N cases per explored FEC" in place of a total, or that the campaign ends with the list of FECs.

### How a campaign that explores runs

The campaign starts with one entry in its FEC list called `exploration`: the exploration itself, one case. When it finishes, one FEC `explored/<five digit index>` appears per FEC found, and their cases run through the later steps. A campaign that only explores ends when the exploration does, and its explored FECs need no cases. An exploration that finds nothing ends the campaign and says why.

## Input

The Input page depends on the first step. A campaign that starts with the design space exploration has nothing to choose here: its FECs come from the exploration, with no catalog scope and no input.

### Scene generation

A functional equivalence class (FEC) is one functional scenario: a scenario of the control node's catalog, or a file you add.

- **Catalog FECs**: pick folders, patterns or FECs from the control node's catalog, each scope entry with a quota and a failure budget.
- **Functional scenario files**: add your own functional scenario files (`.problem` files). Each file is uploaded to the control node when you pick it and becomes a FEC of its own named `scenario/<name>`, with a quota and a failure budget. Give each file a name without a slash; names must differ.

Use either or both. Scope entries without FECs are ignored while there are scenario files.

#### Quota and failure budget

Both apply to each FEC of the entry or file on its own.

- **Quota**: the complete cases the FEC needs. A case is complete when every run has its monitor result summary. A failed monitor result summary is a finding and counts toward the quota.
- **Failure budget**: the cases the FEC may lose before it is abandoned. A case is lost when it is dropped (no valid scene within the timeout, or no complete trajectories) or failed (a job ran out of attempts). A FEC runs at most its quota of cases at once and starts no case it may not need; a lost case is replaced by the next one, with the next seed, once it is lost. Once the lost cases exceed the budget, the FEC is abandoned and its running cases are cancelled.
- **Unlimited**: tick it next to the failure budget and the FEC is never abandoned: it replaces lost cases until its quota is complete. A scenario that never gives a valid scene then runs until a stop condition of the Policy page (a case count or a duration) ends the campaign, or until you stop it. The config says `failure_budget: unlimited`, and Campaign History shows the budget left as unlimited.

#### Seeds

The base seed on the Policy page is where the case seeds start: case k of every FEC gets the base seed + k, and an item (a scene or trajectories a later start takes) gets the base seed + its number in the list. Every step of a case uses its seed: scene generation, trajectory generation and each run, with the ASV system in it. A run can set its own seed on the Simulation page instead. The same config and base seed give the same cases again. The review repeats the base seed, and Campaign History shows it in the header of the entry.

### Trajectory generation and simulation

A campaign that starts with trajectory generation takes **scenes**. One that starts with simulation takes **trajectories**. Each item is one case. Take them from Campaign History, from files, or both.

- **From Campaign History**: choose an entry, then a step of it (the scenes of scene generation, or the planned trajectories of trajectory generation and the recorded trajectories of a simulation run), then add outputs one by one, the outputs shown, or every output of the step (the first 1000 when there are more). Outputs the step dropped or found invalid cannot be added. Each item keeps a link to its source, so Campaign History shows what the campaign was made from.
- **From files**: scene and trajectory files must be JSON. Each file is uploaded to the control node when you pick it and keeps the file name as its source.

Items have a name you can change. Remove items from the chosen list at any time.

### Uploads expire

The control node keeps an uploaded file for 24 hours unless a campaign uses it. A campaign created with the file keeps it for as long as the campaign exists. The wizard shows how long each upload has left and reports an upload that expired, because a config that refers to a deleted file is refused. Upload the file again in that case. Outputs taken from Campaign History are kept by the control node with their entry and do not expire.

## Review and create

The review step checks the config on the control node as soon as it is complete and has stopped changing. Reasons the control node gives are listed with the page and the entry they belong to, such as a scenario file or an input item that no longer exists on the control node. **Create paused** stores the campaign without starting it. **Create and start** also needs a usable machine for every job the steps need; the Resources page lists what is missing. The campaign appears in Campaign History with the kind campaign and the origin wizard.

A draft saved by an earlier version of the wizard opens as a campaign with all three steps, on the Input page in place of the former Scope page.
