import { ToneBadge } from "./campaignParts";
import { STEP_LABELS, type VerdictLine } from "./historyModel";

/** Small pieces the list and the detail of Campaign History share. */

/** Links to the entries this one took its input items from; a name is shown when the page knows it, else the short id. */
export function MadeFrom({ ids, names, onOpen }: { ids: readonly string[]; names: ReadonlyMap<string, string>; onOpen: (campaignId: string) => void }) {
  if (ids.length === 0) {
    return <span className="meta">its own input</span>;
  }
  return (
    <span className="history-made-from">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          className="camp-link"
          title={`Open entry ${id}`}
          aria-label={`Made from ${names.get(id) ?? id}`}
          onClick={(event) => {
            event.stopPropagation();
            onOpen(id);
          }}
        >
          {names.get(id) ?? id.slice(0, 8)}
        </button>
      ))}
    </span>
  );
}

/** The verdicts of each executed step: passed and failed counts. */
export function VerdictChips({ lines }: { lines: readonly VerdictLine[] }) {
  if (lines.length === 0) {
    return null;
  }
  return (
    <span className="history-verdicts">
      {lines.map((line) => (
        <span key={line.step} className="history-verdict-line" title={`Monitor summaries of ${STEP_LABELS[line.step].toLowerCase()}`}>
          <span className="meta">{STEP_LABELS[line.step]}</span>
          {line.passed > 0 && <ToneBadge tone="ok">{line.passed} passed</ToneBadge>}
          {line.failed > 0 && <ToneBadge tone="bad">{line.failed} failed</ToneBadge>}
          {line.unmonitored > 0 && <ToneBadge tone="idle">{line.unmonitored} unmonitored</ToneBadge>}
        </span>
      ))}
    </span>
  );
}
