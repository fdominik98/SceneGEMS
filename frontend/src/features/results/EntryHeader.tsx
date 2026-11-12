import type { CampaignSummary } from "../../domain/cluster/schemas";
import { StateBadge, ToneBadge } from "../history/campaignParts";
import { describeOrigin, executedSteps, hasStepViews, KIND_LABEL, STEP_LABEL } from "./stepViews";

/** Which entry the findings belong to: its name, kind, origin, state and the steps it executed. */
export function EntryHeader({ entry }: { entry: CampaignSummary }) {
  const madeFrom = entry.made_from ?? [];
  const origin = describeOrigin(entry.origin);
  return (
    <header className="results-entry">
      <h2 className="results-entry-name">{entry.name}</h2>
      {entry.kind && <ToneBadge tone={entry.kind === "campaign" ? "info" : "idle"}>{KIND_LABEL[entry.kind]}</ToneBadge>}
      <StateBadge state={entry.actual_state} desired={entry.desired_state} />
      {hasStepViews(entry) && (
        <span className="meta">
          {executedSteps(entry)
            .map((step) => STEP_LABEL[step].toLowerCase())
            .join(", then ")}
          {origin ? `, ${origin}` : ""}
          {madeFrom.length > 0 ? `, built on ${madeFrom.length === 1 ? "entry" : "entries"} ${madeFrom.join(", ")}` : ""}
        </span>
      )}
      {entry.state_reason && <span className="meta">{entry.state_reason}</span>}
    </header>
  );
}
