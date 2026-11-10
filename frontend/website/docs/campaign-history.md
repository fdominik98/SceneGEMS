---
sidebar_position: 19
title: Campaign History
---

# Campaign History

Campaign History lists every entry of the selected cluster, ongoing and finished: the campaigns made in the wizard or on the command line, and every run of the workbench (design space exploration, scene generation, trajectory generation, simulation, recorded live sessions). Each entry runs one or more consecutive steps of the chain design space exploration, scene generation, trajectory generation, simulation, and every step's outputs can be opened on the workbench page of its subsystem.

## The list

Each row shows:

| Column | Description |
|--------|-------------|
| Entry | The name, the kind (campaign or workbench run) and where it was made (the wizard, the command line, a workbench page or a live session; entries made before Campaign History existed say "not recorded") |
| Steps | The steps the entry runs, in chain order |
| State | Created, running, paused, draining, stalled, stopped or completed, with what it is asked to become when that differs |
| Made from | Links to the entries whose outputs this one took as its input; "its own input" when it started from catalog FECs, scenarios or files |
| Totals | Cases by state, and the monitor result summaries of each monitored step |
| Created | When the entry was made |

Filter the list by kind, by state, by step and by a part of the name. The kind, state and name filters are applied by the master; the step filter narrows the page that is shown. The list follows the master's live channel (the badge says **live**); when the channel does not deliver, it is read every 4 seconds (**polling**).

**New campaign** opens the Campaigns page.

### Deleting an entry

**Delete** on a finished entry (stopped or completed) asks for a confirmation, then removes the entry with its cases and outputs. Outputs another entry took as its input stay; that entry's link then reads "a deleted entry". A running entry cannot be deleted: stop it first.

## An entry

Clicking a row opens the entry:

- **Header**: the name, the kind, the state, who made it, what it was made from and its input. **Open the results** shows its findings in Results; **Delete** removes a finished entry. **Entry details** has the id, the times and the config version.
- **Controls** (campaigns only): Start, Pause, Drain, Resume and Stop, each with what it does. A stop is confirmed and cannot be undone.
- **Numbers**: complete cases against the quota, cases in flight and dropped, and the monitor result summaries.
- **Outputs per step**: a tab per executed step with its outputs, a page of 20 at a time.
- **Coverage** (campaigns only): the FECs (functional equivalence classes) with their progress, failure budgets and monitor result summaries per run. A campaign that explores lists `exploration`, labeled as the design space exploration itself, and then the FECs it found as `explored/<index>`. A campaign that only explores shows a tile with the number of explored FECs and says they need no cases.
- **Activity log** and **Config**: the entry's events and its config versions as YAML.

### Outputs of the exploration

The tab of the design space exploration lists the explored FECs with their vessel and obstacle counts, a page of 20 at a time. The step has no monitor, so there are no findings. **Open in workbench** shows the exploration on the Design Space Exploration page with that FEC selected, and **To scene generation** puts the FEC's text into the Scene Generation page's editor under its label, such as `explored/00003`. While the exploration runs, the tab says the FECs appear once it has ended.

### Outputs of a step

| Column | Description |
|--------|-------------|
| Case | The case, its FEC, and the run and repeat of a simulated run |
| State | In progress, complete, dropped, failed or cancelled, with the reason |
| Output | **valid** or **not valid** (the case dropped at this step), and **complete** or **partial** (a trajectory set in which not every vessel reached its goal) |
| Monitor result summary | Only for a step with a monitor configured: whether the monitor passed or failed the output and, per vessel pair, the scenario type, each vessel's role (give-way or stand-on) and the rules that failed. Pairs that never met in an encounter are only counted, and a list longer than three failed rules is cut short: Results has them all. A summary written before the roles were recorded says "roles not recorded" |
| Input from | The case of another entry the input came from (a link), the uploaded file, or "a deleted entry" |

**Open in workbench** loads the output on its page: a scene on Scene Generation, a trajectory set on Trajectory Generation, a simulated run on Simulation (as a replay of its frames with the monitor). A case still working on the step shows **Watch live** instead, which opens the page following the running job.
