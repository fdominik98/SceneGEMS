import { useCallback, useMemo } from "react";
import { useUiStore } from "../../app/uiStore";
import { plural } from "../campaigns/campaignFormat";
import { useCatalogStacks } from "../campaigns/useCampaignData";
import type { BuilderCatalog } from "../campaigns/wizard/configBuilder";
import { draftHasEntries } from "../campaigns/wizard/presetDraft";
import { draftFromStoredConfig, namedAllocation, runsWithoutStack } from "../campaigns/wizard/storedConfigDraft";
import { useWizardStore, type WizardDraft } from "../campaigns/wizard/wizardState";
import { useClusterDomain } from "../domain/useClusterDomain";

/** The campaign and the config version a draft was loaded from. */
export interface ConfigOrigin {
  name: string;
  version: number;
}

/** What the wizard says above its pages after a config was loaded into it. */
export function loadedNotice(origin: ConfigOrigin, draft: WizardDraft, allocation: readonly string[] = []): string {
  const parts = [`Started from the config of "${origin.name}" (version ${origin.version}).`];
  if (draft.input.scenarios.length > 0 || draft.input.items.length > 0) {
    parts.push("Its input is kept.");
  }
  const missing = runsWithoutStack(draft);
  if (missing > 0) {
    parts.push(`${plural(missing, "run")} used a stack this control node does not offer: check the Simulation page.`);
  }
  if (allocation.length > 0) {
    // The wizard offers no allocation: say what the campaign named and that the new one does not
    parts.push(`It named ${allocation.join(", ")}; a campaign made here uses every machine automatically.`);
  }
  parts.push("Adjust it, then create the campaign.");
  return parts.join(" ");
}

export interface LoadIntoWizard {
  /** Why a config cannot be loaded yet, or null when it can. */
  blocker: string | null;
  /** Replaces the wizard's draft with the config (after asking, when the draft holds entries) and opens the Campaigns section. */
  load: (config: Record<string, unknown>, origin: ConfigOrigin) => void;
}

/**
 * Loads a stored campaign config into the create wizard, from Campaign History. The runs of the
 * config are matched against the control node's stack catalog, and its domain contents against the cluster's
 * domain configuration, so both are read first.
 */
export function useLoadIntoWizard(): LoadIntoWizard {
  const stacks = useCatalogStacks();
  const domain = useClusterDomain();
  const catalog = useMemo<BuilderCatalog | null>(() => (stacks.data ? { stacks: stacks.data.stacks, generators: stacks.data.trajectory_generators } : null), [stacks.data]);
  const clusterDomain = domain.data ?? null;
  const waiting = catalog === null || domain.isLoading;

  const load = useCallback(
    (config: Record<string, unknown>, origin: ConfigOrigin) => {
      if (catalog === null) {
        return;
      }
      const wizard = useWizardStore.getState();
      if (draftHasEntries(wizard.draft) && !window.confirm(`Replace the draft in the wizard with the config of "${origin.name}"?`)) {
        return;
      }
      const draft = draftFromStoredConfig(config, catalog, { clusterDomain });
      wizard.replaceDraft(draft, loadedNotice(origin, draft, namedAllocation(config)));
      useUiStore.getState().setSection("campaigns");
    },
    [catalog, clusterDomain]
  );

  let blocker: string | null = null;
  if (waiting) {
    blocker = stacks.isError ? "The control node's stacks could not be read, so the config's runs cannot be matched." : "Waiting for the control node's stacks and domain configuration";
  }
  return { blocker, load };
}
