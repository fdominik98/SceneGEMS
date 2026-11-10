import { useCallback } from "react";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { ArtifactRef } from "../../../domain/cluster/schemas";
import { shortHash } from "../../cluster/clusterFormat";
import { plural } from "../campaignFormat";
import { FieldIssues } from "./fields";
import { HistoryPicker } from "./HistoryPicker";
import { itemFromUpload, uploadNote } from "./inputItems";
import { reasonsOfEntry, splitByField, type Reason } from "./reasons";
import { CAMPAIGN_STEP_LABELS, firstStep, itemKindsFor, sourceStepsFor, uploadKindFor } from "./stepPlan";
import type { StepProps } from "./stepTypes";
import { UploadControl } from "./UploadControl";
import type { InputItemDraft } from "./wizardState";

const ITEM_FIELDS = ["name", "ref"] as const;

function describeSource(item: InputItemDraft): string {
  const source = item.source;
  if ("file" in source) {
    return `file ${source.file}`;
  }
  return `case ${source.case_id} of ${CAMPAIGN_STEP_LABELS[source.step].toLowerCase()}, entry ${shortHash(source.campaign_id, 8)}`;
}

function ItemRow({ item, index, reasons, now, onChange, onRemove }: { item: InputItemDraft; index: number; reasons: readonly Reason[]; now: number; onChange: (change: (item: InputItemDraft) => void) => void; onRemove: () => void }) {
  const { byField, rest } = splitByField(reasons, ITEM_FIELDS);
  return (
    <tr aria-label={`Input item ${index + 1}`} className={reasons.length > 0 ? "wiz-item--invalid" : undefined}>
      <td className="camp-num">{index + 1}</td>
      <td>
        <input type="text" aria-label={`Name of item ${index + 1}`} value={item.name} maxLength={256} onChange={(event) => onChange((entry) => void (entry.name = event.target.value))} />
        <FieldIssues reasons={[...(byField.get("name") ?? []), ...(byField.get("ref") ?? []), ...rest]} showField />
      </td>
      <td title={`${item.ref.sha256}${item.ref.pointer ? ` at ${item.ref.pointer}` : ""}`}>
        {item.ref.kind.replace(/_/g, " ")}, {describeSource(item)}
      </td>
      <td>{uploadNote(item.uploadedAt, now)}</td>
      <td>
        <button type="button" className="wiz-remove" aria-label={`Remove item ${index + 1}`} onClick={onRemove}>
          Remove
        </button>
      </td>
    </tr>
  );
}

/**
 * The input of a campaign that starts after scene generation: scenes (trajectory generation) or
 * trajectories (simulation), taken from Campaign History or uploaded as files. Each becomes one
 * class of one case.
 */
export function ItemInput({ draft, update, reasons, client, now }: StepProps & { client: OperatorClient | null; now: number }) {
  const first = firstStep(draft.steps);
  const kinds = itemKindsFor(draft.steps);
  const uploadKind = uploadKindFor(draft.steps) ?? "scene";
  const noun = first === "trajectory_generation" ? "scenes" : "trajectories";
  const items = draft.input.items;

  const add = useCallback(
    (added: InputItemDraft[]) => {
      if (added.length > 0) {
        update((next) => void next.input.items.push(...added));
      }
    },
    [update]
  );
  const onUploaded = useCallback(
    (fileName: string, ref: ArtifactRef) =>
      update((next) => {
        next.input.items.push(itemFromUpload(fileName, ref, next.input.items.map((item) => item.name.trim()), Date.now()));
      }),
    [update]
  );
  const change = (id: string, edit: (item: InputItemDraft) => void) =>
    update((next) => {
      const found = next.input.items.find((item) => item.id === id);
      if (found) {
        edit(found);
      }
    });
  const own = reasonsOfEntry(reasons, null).filter((reason) => reason.field === "items" || reason.field === "input" || reason.field === "scope" || reason.field === "functional_scenarios");

  return (
    <div className="wiz-step">
      <p className="meta wiz-explain">
        {first === "trajectory_generation"
          ? "Trajectory generation plans the trajectories of scenes you already have. Each scene is one case."
          : "Simulation runs trajectories you already have: every run of the Simulation page is simulated for each of them."}
      </p>
      <FieldIssues reasons={own} showField />

      <section className="wiz-subsection wiz-subsection--first" aria-label="From Campaign History">
        <div className="wiz-column">
          <h4 className="wiz-subhead">From Campaign History</h4>
          <HistoryPicker client={client} sourceSteps={sourceStepsFor(draft.steps)} kinds={kinds} noun={noun} items={items} onAdd={add} />
        </div>
      </section>
      <section className="wiz-subsection" aria-label="From files">
        <div className="wiz-column">
          <h4 className="wiz-subhead">From files</h4>
          <p className="meta wiz-explain">
            A file is uploaded to the control node as soon as you pick it and used as one {first === "trajectory_generation" ? "scene" : "trajectory set"}. Uploaded files are kept for 24 hours; a campaign created with them keeps them.
          </p>
          <UploadControl client={client} kind={uploadKind} label={first === "trajectory_generation" ? "Add scene files (JSON)" : "Add trajectory files (JSON)"} accept=".json,application/json" onUploaded={onUploaded} />
        </div>
      </section>

      <h4 className="wiz-subhead">Chosen input ({plural(items.length, "item")})</h4>
      {items.length === 0 && <p className="meta">Nothing chosen yet. Pick {noun} from Campaign History or add files.</p>}
      {items.length > 0 && (
        <div className="camp-table-wrap wiz-class-scroll">
          <table className="camp-table camp-table--dense">
            <thead>
              <tr>
                <th>#</th>
                <th>Name</th>
                <th>Source</th>
                <th>Kept</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item, index) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  index={index}
                  reasons={reasonsOfEntry(reasons, index, "item")}
                  now={now}
                  onChange={(edit) => change(item.id, edit)}
                  onRemove={() => update((next) => void (next.input.items = next.input.items.filter((entry) => entry.id !== item.id)))}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      {items.length > 1 && (
        <div>
          <button type="button" className="wiz-remove" onClick={() => update((next) => void (next.input.items = []))}>
            Remove all items
          </button>
        </div>
      )}
    </div>
  );
}
