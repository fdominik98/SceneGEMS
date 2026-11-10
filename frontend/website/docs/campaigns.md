---
sidebar_position: 18
title: Campaigns
---

# Campaigns

The Campaigns page defines a campaign and starts it on the selected cluster. Following, controlling and deleting campaigns happens in [Campaign History](./campaign-history.md), which the page opens with **Open Campaign History**.

## The wizard

The wizard builds the campaign config step by step: the steps of the chain the campaign runs (design space exploration, scene generation, trajectory generation, simulation) and their monitors, the input (none when the campaign explores), the domain, the trajectory generator, the runs, the resources and the policy. The review step checks the config on the master before the campaign is created. What you enter is kept in this browser until the campaign is created or you discard it.

Once created, the campaign opens in Campaign History, where it can be started (unless it was started on creation) and followed.

| Wizard action | What it does |
|---------------|--------------|
| Create paused | Creates the campaign; it holds its jobs until you start it in Campaign History |
| Create and start | Creates the campaign and starts it at once (off while no machine offers a job type it needs) |
| Close, keep the draft | Leaves the wizard for Campaign History; the draft waits in this browser |
| Discard the draft | Forgets everything entered in the wizard |
