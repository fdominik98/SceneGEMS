import { useState } from "react";
import { Disclosure } from "../../../components/Disclosure";
import { describeOperatorError, OperatorApiError } from "../../../domain/cluster/operatorApi";
import type { CampaignPreset } from "../../../domain/cluster/presetsApi";
import type { BuilderCatalog } from "./configBuilder";
import { draftFromConfig, draftHasEntries, presetConfigOf } from "./presetDraft";
import { CAMPAIGN_STEP_LABELS } from "./stepPlan";
import { useCampaignPresets, useDeleteCampaignPreset, useSaveCampaignPreset } from "./useCampaignPresets";
import type { WizardDraft } from "./wizardState";

interface PresetBarProps {
  draft: WizardDraft;
  /** The stacks and generators the master offers; null while they load (a preset's runs need them). */
  catalog: BuilderCatalog | null;
  onLoad: (draft: WizardDraft) => void;
}

function stepsOf(preset: CampaignPreset): string {
  return preset.steps.map((step) => CAMPAIGN_STEP_LABELS[step]).join(", ");
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

/**
 * Campaign presets of the master: start the wizard from one of them (the ones the master image
 * ships for campaign runs that come up again and again, or ones saved on this cluster), or save the
 * current draft as a preset for the next time.
 */
export function PresetBar({ draft, catalog, onLoad }: PresetBarProps) {
  const presets = useCampaignPresets();
  const save = useSaveCampaignPreset();
  const remove = useDeleteCampaignPreset();
  const [chosenId, setChosenId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [replace, setReplace] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const all = presets.data ?? [];
  const shipped = all.filter((preset) => preset.builtin);
  const saved = all.filter((preset) => !preset.builtin);
  const chosen = all.find((preset) => preset.preset_id === chosenId) ?? null;

  const load = () => {
    if (!chosen || !catalog) {
      return;
    }
    if (draftHasEntries(draft) && !window.confirm(`Replace the current draft with the preset "${chosen.name}"?`)) {
      return;
    }
    onLoad(draftFromConfig(chosen.config, catalog));
    setNotice(`Started from the preset "${chosen.name}". Adjust it, then create the campaign.`);
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
          setChosenId(preset.preset_id);
          setNotice(`Saved the preset "${preset.name}" on the master.`);
        },
      }
    );
  };

  const deleteChosen = () => {
    if (!chosen || chosen.builtin || !window.confirm(`Delete the preset "${chosen.name}" from the master?`)) {
      return;
    }
    remove.mutate(chosen.preset_id, {
      onSuccess: () => {
        setChosenId("");
        setNotice(`Deleted the preset "${chosen.name}".`);
      },
    });
  };

  return (
    <section className="wiz-presets panel" aria-label="Campaign presets">
      <div className="wiz-presets-row">
        <label className="wiz-presets-pick">
          <span className="wiz-presets-label">Start from a preset</span>
          <select value={chosenId} onChange={(event) => setChosenId(event.target.value)} disabled={presets.isLoading || all.length === 0} aria-label="Campaign preset">
            <option value="">{presets.isLoading ? "Reading the master's presets..." : all.length === 0 ? "The master offers no presets" : "Choose a preset..."}</option>
            {shipped.length > 0 && (
              <optgroup label="Shipped with the master">
                {shipped.map((preset) => (
                  <option key={preset.preset_id} value={preset.preset_id}>
                    {preset.name}
                  </option>
                ))}
              </optgroup>
            )}
            {saved.length > 0 && (
              <optgroup label="Saved on this cluster">
                {saved.map((preset) => (
                  <option key={preset.preset_id} value={preset.preset_id}>
                    {preset.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
        <button type="button" className="primary-btn" disabled={!chosen || !catalog} onClick={load} title={catalog ? undefined : "Waiting for the master's stacks"}>
          Load into the wizard
        </button>
        {chosen && !chosen.builtin && (
          <button type="button" className="wiz-remove" disabled={remove.isPending} onClick={deleteChosen}>
            Delete the preset
          </button>
        )}
      </div>
      {chosen && (
        <p className="meta wiz-presets-description">
          {chosen.description || "No description."} <span className="wiz-presets-steps">Steps: {stepsOf(chosen)}.</span>
        </p>
      )}
      {presets.isError && <p className="error">The presets could not be read: {describeOperatorError(presets.error)}</p>}
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
          <p className="meta">The preset keeps the steps, scope, domain, trajectories, runs, resources and policy. Uploaded files and picked outputs belong to one campaign and are not saved.</p>
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
