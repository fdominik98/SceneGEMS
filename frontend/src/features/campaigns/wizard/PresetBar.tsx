import { useMemo, useState } from "react";
import { Disclosure } from "../../../components/Disclosure";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { describeOperatorError, OperatorApiError } from "../../../domain/cluster/operatorApi";
import type { CampaignPreset } from "../../../domain/cluster/presetsApi";
import { CatalogDialog } from "./CatalogDialog";
import type { BuilderCatalog } from "./configBuilder";
import { describeSteps, PRESET_CATALOG, presetFacts, scopeTags, type PresetFacts } from "./presetCatalog";
import { draftFromConfig, draftHasEntries, presetConfigOf } from "./presetDraft";
import { useCampaignPresets, useDeleteCampaignPreset, useSaveCampaignPreset } from "./useCampaignPresets";
import type { WizardDraft } from "./wizardState";

interface PresetBarProps {
  draft: WizardDraft;
  /** The stacks and generators the master offers; null while they load (a preset's runs need them). */
  catalog: BuilderCatalog | null;
  /** The master's FEC catalog, to say what a preset's scope selects; undefined while it loads. */
  classes?: readonly CatalogClass[];
  onLoad: (draft: WizardDraft) => void;
}

function failure(error: unknown): string {
  if (error instanceof OperatorApiError && error.status === 409) {
    return error.message;
  }
  if (error instanceof OperatorApiError && error.reasons.length > 0) {
    return `${error.message}: ${error.reasons.join("; ")}`;
  }
  return describeOperatorError(error);
}

function PresetCard({ facts, canLoad, deleting, onLoad, onDelete }: { facts: PresetFacts; canLoad: boolean; deleting: boolean; onLoad: () => void; onDelete: () => void }) {
  const { preset } = facts;
  const tags = [...scopeTags(facts), ...facts.stacks.map((stack) => stack.label), describeSteps(preset.steps)];
  return (
    <article className="wiz-catalog-item" aria-label={preset.name}>
      <div className="wiz-catalog-item-head">
        <strong>{preset.name}</strong>
        {!preset.builtin && <span className="wiz-catalog-badge">Saved</span>}
      </div>
      <p className="wiz-catalog-item-text">{preset.description || "No description."}</p>
      <div className="wiz-catalog-tags">
        {tags.map((tag) => (
          <span key={tag} className="wiz-catalog-tag">
            {tag}
          </span>
        ))}
      </div>
      {facts.blocked && <p className="wiz-catalog-warning">A run needs a stack this master cannot run: load it and pick another stack on the Simulation page.</p>}
      <div className="wiz-catalog-item-actions">
        <button type="button" className="primary-btn" disabled={!canLoad} onClick={onLoad} title={canLoad ? undefined : "Waiting for the master's stacks"}>
          Load into the wizard
        </button>
        {!preset.builtin && (
          <button type="button" className="wiz-remove" disabled={deleting} onClick={onDelete}>
            Delete the preset
          </button>
        )}
      </div>
    </article>
  );
}

/**
 * Campaign presets of the master: start the wizard from one of them (the ones the master image
 * ships for campaign runs that come up again and again, or ones saved on this cluster), found in the
 * preset catalog, or save the current draft as a preset for the next time.
 */
export function PresetBar({ draft, catalog, classes, onLoad }: PresetBarProps) {
  const presets = useCampaignPresets();
  const save = useSaveCampaignPreset();
  const remove = useDeleteCampaignPreset();
  const [browsing, setBrowsing] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [replace, setReplace] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const facts = useMemo(() => (presets.data ?? []).map((preset) => presetFacts(preset, catalog, classes)), [presets.data, catalog, classes]);

  const load = (preset: CampaignPreset) => {
    if (!catalog) {
      return;
    }
    if (draftHasEntries(draft) && !window.confirm(`Replace the current draft with the preset "${preset.name}"?`)) {
      return;
    }
    onLoad(draftFromConfig(preset.config, catalog));
    setBrowsing(false);
    setNotice(`Started from the preset "${preset.name}". Adjust it, then create the campaign.`);
  };

  const saveDraft = () => {
    if (!catalog) {
      return;
    }
    const presetName = (name.trim() || draft.name.trim()).slice(0, 200);
    setNotice(null);
    save.mutate(
      { name: presetName, description: description.trim() || draft.description.trim(), config: presetConfigOf(draft, catalog), replace },
      {
        onSuccess: (preset) => {
          setNotice(`Saved the preset "${preset.name}" on the master.`);
        },
      }
    );
  };

  const deletePreset = (preset: CampaignPreset) => {
    if (preset.builtin || !window.confirm(`Delete the preset "${preset.name}" from the master?`)) {
      return;
    }
    remove.mutate(preset.preset_id, {
      onSuccess: () => {
        setNotice(`Deleted the preset "${preset.name}".`);
      },
    });
  };

  return (
    <section className="wiz-presets" aria-label="Campaign presets">
      <div className="wiz-presets-row">
        <span className="wiz-presets-label">Start from a preset</span>
        <button type="button" aria-haspopup="dialog" disabled={presets.isLoading || facts.length === 0} onClick={() => setBrowsing(true)}>
          {presets.isLoading ? "Reading the master's presets..." : facts.length === 0 ? "The master offers no presets" : `Browse ${facts.length} presets`}
        </button>
      </div>
      {presets.isError && <p className="error">The presets could not be read: {describeOperatorError(presets.error)}</p>}
      {browsing && (
        <CatalogDialog
          title="Campaign presets"
          noun="preset"
          storageKey="presets"
          items={facts}
          model={PRESET_CATALOG}
          onClose={() => setBrowsing(false)}
          renderItem={(item) => <PresetCard facts={item} canLoad={catalog !== null} deleting={remove.isPending} onLoad={() => load(item.preset)} onDelete={() => deletePreset(item.preset)} />}
        />
      )}
      <Disclosure id="wizard:save-preset" variant="link" headingLevel={null} title="Save this draft as a preset" openTitle="Hide saving as a preset">
        <div className="wiz-presets-save">
          <label>
            <span>Preset name</span>
            <input type="text" value={name} maxLength={200} placeholder={draft.name.trim() || "A name to find it by"} onChange={(event) => setName(event.target.value)} />
          </label>
          <label>
            <span>Description</span>
            <textarea rows={2} value={description} placeholder={draft.description.trim() || "What the campaign checks, and when to run it"} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <label className="wiz-check">
            <input type="checkbox" checked={replace} onChange={(event) => setReplace(event.target.checked)} />
            Replace a saved preset of the same name
          </label>
          <p className="meta wiz-explain">The preset keeps the steps, scope, domain, trajectories, runs, resources and policy. Uploaded files and picked outputs belong to one campaign and are not saved.</p>
          <button type="button" disabled={!catalog || save.isPending || !(name.trim() || draft.name.trim())} onClick={saveDraft}>
            {save.isPending ? "Saving..." : "Save as preset"}
          </button>
        </div>
      </Disclosure>
      {save.isError && (
        <p className="error" role="alert">
          The preset was not saved: {failure(save.error)}
        </p>
      )}
      {remove.isError && (
        <p className="error" role="alert">
          The preset was not deleted: {failure(remove.error)}
        </p>
      )}
      {notice && (
        <p className="meta" role="status">
          {notice}
        </p>
      )}
    </section>
  );
}
