import type { CSSProperties } from "react";
import { NumberField } from "../../campaigns/wizard/fields";
import { MAX_ENTRY_SEED } from "./entryConfig";
import { useEntrySeedStore } from "./entrySeedStore";
import "./pages.css";

/**
 * The base seed of the page's next entry, as a setting on one line. Empty draws a fresh random
 * seed per run; a number repeats a run. Every step of the entry's case uses it. The seed of the
 * last run can be kept.
 */
export function EntrySeedField({ disabled = false }: { disabled?: boolean }) {
  const fixed = useEntrySeedStore((state) => state.fixed);
  const last = useEntrySeedStore((state) => state.last);
  const setFixed = useEntrySeedStore((state) => state.setFixed);
  const note =
    fixed !== null
      ? "Every run uses this seed in each step."
      : last !== null
        ? `A new random seed per run; the last run used ${last}.`
        : "A new random seed per run.";
  return (
    <span className="step-setting step-number entry-seed" title={note} style={{ "--field-ch": 10 } as CSSProperties}>
      <span className="step-setting-label" aria-hidden>
        Seed
      </span>
      <NumberField integer min={0} max={MAX_ENTRY_SEED} value={fixed} placeholder="random" ariaLabel="Base seed" onChange={setFixed} disabled={disabled} />
      {fixed === null && last !== null && (
        <button type="button" className="link-btn" title="Use the seed of the last run for every run" onClick={() => setFixed(last)} disabled={disabled}>
          Keep {last}
        </button>
      )}
    </span>
  );
}
