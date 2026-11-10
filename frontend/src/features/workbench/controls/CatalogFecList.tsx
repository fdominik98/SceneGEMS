import { useLayoutEffect, useRef, useState } from "react";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { fecRelationSummary } from "../../../domain/designSpace/fecRelations";
import { FEC_ROW_HEIGHT, visibleRange } from "../designSpace/explorationModel";
import { useCatalogTexts } from "./catalogTexts";

/** The list's height before it is measured (and where nothing measures, as in tests). */
const FALLBACK_HEIGHT = 480;

function counts(entry: CatalogClass): string {
  return `${entry.vessel_count} vessel${entry.vessel_count === 1 ? "" : "s"}, ${entry.obstacle_count} obstacle${entry.obstacle_count === 1 ? "" : "s"}`;
}

interface Props {
  /** The catalog FECs the filters match. */
  presets: CatalogClass[];
  selected: ReadonlySet<string>;
  /** The FEC shown in the preview, null for none. */
  previewId: string | null;
  disabled: boolean;
  onToggle: (classId: string) => void;
  onPreview: (classId: string) => void;
  /** The class ids of the rows drawn now, so their texts are read. */
  onShownRows: (classIds: string[]) => void;
}

/**
 * The catalog FECs as a windowed list: a row per FEC with its checkbox (the selection the run
 * takes), its counts and, once its text is read, its relations in words. Only the rows in view are
 * drawn, so all 828 FECs of the catalog scroll smoothly. A row's body previews the FEC without
 * selecting it.
 */
export function CatalogFecList({ presets, selected, previewId, disabled, onToggle, onPreview, onShownRows }: Props) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ top: 0, height: FALLBACK_HEIGHT });
  const texts = useCatalogTexts((s) => s.texts);
  const errors = useCatalogTexts((s) => s.errors);

  useLayoutEffect(() => {
    const element = listRef.current;
    if (element === null) {
      return;
    }
    const measure = () => setView((current) => ({ ...current, height: element.clientHeight || FALLBACK_HEIGHT }));
    measure();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, []);

  const { first, last } = visibleRange(presets.length, view.top, view.height);
  const shown = presets.slice(first, last);
  const shownKey = shown.map((entry) => entry.fec_id).join("|");
  const reported = useRef("");
  useLayoutEffect(() => {
    if (reported.current !== shownKey) {
      reported.current = shownKey;
      onShownRows(shownKey.length === 0 ? [] : shownKey.split("|"));
    }
  }, [onShownRows, shownKey]);

  return (
    <div
      ref={listRef}
      className="fec-pick-list"
      onScroll={(event) => {
        const top = event.currentTarget.scrollTop;
        setView((current) => (current.top === top ? current : { ...current, top }));
      }}
    >
      <ul className="fec-pick-space" aria-label="FECs of the control node's catalog" style={{ height: presets.length * FEC_ROW_HEIGHT }}>
        {shown.map((entry, offset) => {
          const text = texts[entry.fec_id];
          const error = errors[entry.fec_id];
          const relations = text !== undefined ? fecRelationSummary(text) : error !== undefined ? "text not readable" : "reading its relations...";
          const isSelected = selected.has(entry.fec_id);
          return (
            <li
              key={entry.fec_id}
              className={`fec-pick-row${isSelected ? " is-selected" : ""}${previewId === entry.fec_id ? " is-previewed" : ""}`}
              style={{ top: (first + offset) * FEC_ROW_HEIGHT, height: FEC_ROW_HEIGHT }}
            >
              <input type="checkbox" aria-label={entry.fec_id} checked={isSelected} disabled={disabled} onChange={() => onToggle(entry.fec_id)} />
              <button type="button" className="fec-pick-body" aria-label={`Preview ${entry.fec_id}`} aria-pressed={previewId === entry.fec_id} title={text !== undefined ? relations : error} onClick={() => onPreview(entry.fec_id)}>
                <span className="fec-pick-head">
                  <span className="fec-pick-id">{entry.fec_id}</span>
                  <span className="fec-pick-counts">{counts(entry)}</span>
                </span>
                <span className={`fec-pick-relations${text === undefined ? " is-pending" : ""}`}>{relations}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
