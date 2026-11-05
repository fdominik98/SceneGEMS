import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { usePersistedState } from "../../../app/usePersistedState";
import { EmptyState } from "../../../components/EmptyState";
import { IconButton } from "../../../components/IconButton";
import { CloseIcon } from "../../../components/icons";
import { plural } from "../campaignFormat";
import { activePicks, facetViews, filterCatalog, groupCatalog, picksFromStorage, togglePick, type CatalogModel, type FacetView } from "./catalogModel";

interface CatalogDialogProps<T> {
  title: string;
  /** What one item is called, for the search box and the counts. */
  noun: string;
  /** Names what this browser remembers: the catalog's filters and grouping. */
  storageKey: string;
  items: readonly T[];
  model: CatalogModel<T>;
  renderItem: (item: T) => ReactNode;
  onClose: () => void;
}

const FOCUSABLE = ":is(button, input, select, a[href]):not(:disabled)";

function FacetFilter({ facet, onToggle }: { facet: FacetView; onToggle: (value: string) => void }) {
  return (
    <fieldset className="wiz-catalog-facet">
      <legend>{facet.label}</legend>
      {facet.options.map((option) => (
        <label key={option.value} className={`wiz-catalog-option${option.count === 0 && !option.picked ? " wiz-catalog-option--empty" : ""}`}>
          <input type="checkbox" checked={option.picked} onChange={() => onToggle(option.value)} />
          <span className="wiz-catalog-option-label">{option.label}</span>
          <span className="wiz-catalog-count" aria-label={plural(option.count, "match", "matches")}>
            {option.count}
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/**
 * A catalog to pick from: search, filters and a grouping over the items, each item drawn by the
 * caller. Laid over the page in a fixed layer (the scrollbars' layer stays above it, which a native
 * modal dialog would cover), it takes the focus and gives it back when it closes.
 */
export function CatalogDialog<T>({ title, noun, storageKey, items, model, renderItem, onClose }: CatalogDialogProps<T>) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [storedPicks, setStoredPicks] = usePersistedState<unknown>(`wizard-catalog:${storageKey}:filters`, {});
  const [groupBy, setGroupBy] = usePersistedState<string>(`wizard-catalog:${storageKey}:group-by`, "");

  const picks = useMemo(() => activePicks(items, model, picksFromStorage(storedPicks)), [items, model, storedPicks]);
  const facets = useMemo(() => facetViews(items, model, picks, query), [items, model, picks, query]);
  const shown = useMemo(() => filterCatalog(items, model, picks, query), [items, model, picks, query]);
  const grouping = model.groupings.find((entry) => entry.key === groupBy) ?? model.groupings[0];
  const groups = useMemo(() => groupCatalog(shown, grouping), [shown, grouping]);
  const filtered = Object.keys(picks).length > 0 || query.trim() !== "";

  useEffect(() => {
    const opener = document.activeElement;
    searchRef.current?.focus();
    return () => {
      if (opener instanceof HTMLElement) {
        opener.focus();
      }
    };
  }, []);

  const clear = () => {
    setStoredPicks({});
    setQuery("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab" || !dialogRef.current) {
      return;
    }
    // The page behind stays out of the tab order
    const focusable = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className="wiz-catalog-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div ref={dialogRef} className="wiz-catalog" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <header className="wiz-catalog-head">
          <h3 id={titleId}>{title}</h3>
          <input ref={searchRef} type="search" placeholder={`Find a ${noun}`} aria-label={`Find a ${noun}`} value={query} onChange={(event) => setQuery(event.target.value)} />
          <IconButton label="Close the catalog" icon={<CloseIcon />} onClick={onClose} />
        </header>
        <div className="wiz-catalog-body">
          <aside className="wiz-catalog-filters" aria-label="Filters">
            {facets.map((facet) => (
              <FacetFilter key={facet.key} facet={facet} onToggle={(value) => setStoredPicks(togglePick(picks, facet.key, value))} />
            ))}
          </aside>
          <div className="wiz-catalog-results">
            <div className="wiz-catalog-bar">
              <span className="meta" role="status">
                {filtered ? `${shown.length} of ${plural(items.length, noun)}` : plural(items.length, noun)}
              </span>
              <button type="button" disabled={!filtered} onClick={clear}>
                Clear filters
              </button>
              <label className="wiz-catalog-group-by">
                <span>Group by</span>
                <select value={grouping.key} onChange={(event) => setGroupBy(event.target.value)}>
                  {model.groupings.map((entry) => (
                    <option key={entry.key} value={entry.key}>
                      {entry.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {shown.length === 0 && <EmptyState title={`No ${noun} matches`}>Clear the filters or try other words.</EmptyState>}
            {groups.map((group) => (
              <section key={group.value} className="wiz-catalog-group" aria-label={group.label}>
                <h4>
                  {group.label} <span className="wiz-catalog-count">{group.items.length}</span>
                </h4>
                <ul className="wiz-catalog-grid">
                  {group.items.map((item) => (
                    <li key={model.idOf(item)}>{renderItem(item)}</li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
