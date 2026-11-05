---
sidebar_position: 16
title: Results
---

# Results

The Results page summarizes the monitor findings of one entry of Campaign History: a campaign made in the Campaigns wizard, or a run of the workbench. It needs a selected cluster (see the Cluster page).

## Pick an entry

The header holds three controls:

- **Show** limits the list to campaigns only or to workbench runs only.
- **Name** keeps the entries whose name contains the text you type.
- **Entry** chooses the entry. Each option shows its name, its kind, its state and its creation time. The newest entry is shown until you choose another one. When the list is cut short, the page says how many entries the master has.

Other pages open Results on an entry for you, for example **Open the results** on an entry of Campaign History. If someone deleted the entry meanwhile, the page says so and offers the newest entry instead.

## Views per step

A campaign or workbench run executes one, two or three consecutive steps of the chain scene generation, trajectory generation, simulation. The row of tabs under the entry name offers only the steps the entry executed, and opens on the last one. Each tab shows the findings of that step and its monitor summaries.

## Findings

The findings panel of a step shows:

- **Monitor summaries**: how many cases passed and how many failed, when a monitor judged the step.
- **Valid and complete outputs**: how many scenes, trajectory sets or simulated runs the step produced, how many were valid and, for trajectories and runs, how many were complete. A trajectory set can be incomplete; when trajectory generation is the last step of an entry, the incomplete set is kept so you can inspect it.
- **Cases by state**: complete, active, dropped, failed or cancelled cases that reached the step.
- **Generation time**: the median and the 90th percentile of the jobs that produced the step's output.
- **Which rules failed**: the rules ranked by the number of monitor summaries they failed in, each with the earliest failure time and the median of the first failure times. A rule that failed for several vessel pairs counts once per monitor summary.
- **Encounter types**: how many vessel pairs met in each encounter type, by the first type of each pair.
- **Per FEC**: cases, passed and failed per FEC (functional equivalence class), most failures first.

### Partial findings

A step is monitored only when the campaign asked for a monitor after it. For a step without a monitor, the page shows the statistics only (outputs, cases, generation time and FECs), marks the panel "partial findings" and says plainly that no monitor judged the step. There are no monitor summaries or failed rules to show, so the monitor summary table is replaced by a note and a button that opens Campaign History, where the outputs of the step are listed.

## Monitor summary table

Below the findings, the table lists the monitor summaries of the shown step, one row per case (scene and trajectory steps) or per run (simulation). You can filter by FEC, state, run and sensitivity, sort by FEC, case and run, page through the rows, and download the filtered rows as CSV. For the simulation step, a second panel counts the monitor summaries of the filtered rows per run. Select a row to open its case.

## Case page

The case page starts with a table of all three steps of the chain: for each step, whether the entry executed it, what the case has of its output, and the step's monitor summary with the failed rules. Under it are the monitor summary cards of every monitored step with the outcome of each rule per vessel pair, the run records, the recorded run and the jobs of the case.

### Recorded run

For a simulated run, **Show the run** fetches the frames of the run with the monitor's outcome on demand. This starts a job on the cluster, so it can take a while. If the job fails or is cancelled, **Try again** or **Run the job again** submits a new one.

## Campaigns made before partial campaigns

A campaign that a master created before this release has no step list. Results then shows its simulation monitor summaries as before, without step tabs and findings.
