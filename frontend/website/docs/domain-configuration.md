---
sidebar_position: 4
title: Domain Configuration
---

# Domain Configuration

Domain Configuration defines the maritime domain model that scene generation and the COLREGS monitor use: the COLREGS constants, the vessel types and the static obstacle types. It is a setting of the cluster, not of the workbench: the master keeps one domain configuration per cluster, and every workbench run and every campaign without domain content of its own uses it. The page is in the Cluster group of the left pane and shows the configuration of the active cluster.

## Tabs

- **Collision rules (COLREGS)**: the constants of the collision avoidance rules.
- **Vessel types**: the vessel type definitions.
- **Static obstacle types**: the static obstacle type definitions.

Each text has its own tab, so its form or YAML editor takes the full width of the page.

## Per-text tools

| Action | Description |
|--------|-------------|
| Load a preset of the master | The presets the master ships (`backend/assets/domain_config/`); the default one is marked. The select shows which preset a text is, or "Edited" when it is none of them |
| Load from computer | Import a local `.yaml` / `.yml` file |
| Export as YAML file | Download the text |

## Saving

Edits stay a draft in the page until **Save to the cluster**: then the master checks each text (it must be a YAML mapping) and stores the three, and from then on every new run uses them. **Discard changes** returns to the saved texts, and **Load the default presets** fills in the master's default presets (save to apply them). Until a cluster saves a configuration, the master's default presets apply.

A campaign keeps the texts it was created with: the master writes the cluster's configuration into the campaign's config, so changing the configuration later does not change campaigns that exist. A campaign can also carry customized texts of its own (the Domain page of the [campaign wizard](./campaign-wizard.md)).

A master that runs without its database keeps no configuration of its own: the page says so, and every run uses the default presets.
