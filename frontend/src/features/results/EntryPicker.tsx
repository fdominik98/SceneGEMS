import type { CampaignSummary } from "../../domain/cluster/schemas";
import { entryOption, type KindFilter } from "./stepViews";

interface EntryPickerProps {
  entries: readonly CampaignSummary[];
  /** The entries the control node has for the filters; more than `entries` when the list is cut short. */
  total: number | null;
  loading: boolean;
  /** The shown entry, which may not be among `entries` (another filter, or a list that is still loading). */
  selectedId: string | null;
  selected: CampaignSummary | null;
  kind: KindFilter;
  name: string;
  onKind: (kind: KindFilter) => void;
  onName: (name: string) => void;
  onPick: (campaignId: string) => void;
}

/** Picks the entry of Campaign History whose findings are shown: filter by kind and name, then choose. */
export function EntryPicker({ entries, total, loading, selectedId, selected, kind, name, onKind, onName, onPick }: EntryPickerProps) {
  const listed = selectedId !== null && entries.some((entry) => entry.campaign_id === selectedId);
  const filtered = kind !== "any" || name.trim() !== "";
  const empty = entries.length === 0;
  return (
    <div className="results-picker" role="group" aria-label="Entry of Campaign History">
      <label>
        <span>Show</span>
        <select value={kind} onChange={(event) => onKind(event.target.value as KindFilter)} aria-label="Kind of entry">
          <option value="any">Campaigns and workbench runs</option>
          <option value="campaign">Campaigns only</option>
          <option value="workbench">Workbench runs only</option>
        </select>
      </label>
      <label>
        <span>Name</span>
        <input type="search" value={name} onChange={(event) => onName(event.target.value)} placeholder="contains" aria-label="Name contains" />
      </label>
      <label className="results-picker-entry">
        <span>Entry</span>
        <select value={selectedId ?? ""} onChange={(event) => onPick(event.target.value)} disabled={empty && selectedId === null} aria-label="Entry">
          {selectedId !== null && !listed && <option value={selectedId}>{selected ? entryOption(selected) : selectedId}</option>}
          {empty && selectedId === null && <option value="">{loading ? "Loading" : filtered ? "No entry matches" : "No entries"}</option>}
          {entries.map((entry) => (
            <option key={entry.campaign_id} value={entry.campaign_id}>
              {entryOption(entry)}
            </option>
          ))}
        </select>
      </label>
      {total !== null && total > entries.length && (
        <span className="meta">
          newest {entries.length} of {total}, narrow by name
        </span>
      )}
    </div>
  );
}
