import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { EmptyState } from "../../../components/EmptyState";
import { LoadingSpinner } from "../../../components/LoadingSpinner";
import { describeExploration } from "../../../domain/designSpace/explorationResult";
import { fecRelationSummary } from "../../../domain/designSpace/fecRelations";
import { ProblemEditor } from "../controls/ProblemEditor";
import { FEC_ROW_HEIGHT, fecCounts, visibleRange } from "./explorationModel";
import { useExplorationStore } from "./explorationStore";
import { loadFecTexts, type TextClient } from "./fecTexts";
import { ModelGraph } from "./graphs/ModelGraph";
import { FEC_VIEW_KEY, useTextOrGraph } from "./graphs/textOrGraph";
import { ViewSwitch } from "./graphs/ViewSwitch";
import "./designSpace.css";

/** The list's height before it is measured (and where nothing measures, as in tests). */
const FALLBACK_HEIGHT = 480;

interface Props {
  client: TextClient | null;
}

/**
 * The centre of the design space exploration page: how many FECs the exploration found and what
 * that means, the list of them (id, vessels, obstacles and, once its text is read, its relations in
 * words), and the selected FEC: its model graph or its whole text, read only (kept per browser). Texts are read for the rows in view and the
 * selected row only.
 */
export function ExploredFecList({ client }: Props) {
  const fecs = useExplorationStore((s) => s.fecs);
  const result = useExplorationStore((s) => s.result);
  const campaignId = useExplorationStore((s) => s.campaignId);
  const running = useExplorationStore((s) => s.running);
  const texts = useExplorationStore((s) => s.texts);
  const textErrors = useExplorationStore((s) => s.textErrors);
  const selectedFecId = useExplorationStore((s) => s.selectedFecId);
  const select = useExplorationStore((s) => s.select);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [view, setView] = useState({ top: 0, height: FALLBACK_HEIGHT });
  const hasRows = fecs.length > 0;
  const [detailView, setDetailView] = useTextOrGraph(FEC_VIEW_KEY, "graph");

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
  }, [campaignId, hasRows]);

  const { first, last } = visibleRange(fecs.length, view.top, view.height);
  const shownIds = useMemo(() => fecs.slice(first, last).map((fec) => fec.fecId), [fecs, first, last]);

  useEffect(() => {
    if (client === null) {
      return;
    }
    void loadFecTexts(client, selectedFecId !== null ? [selectedFecId, ...shownIds] : shownIds);
  }, [client, selectedFecId, shownIds]);

  const selected = fecs.find((fec) => fec.fecId === selectedFecId) ?? null;
  const selectedIndex = selected === null ? -1 : fecs.indexOf(selected);

  const moveSelection = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
    if (step === 0 || fecs.length === 0) {
      return;
    }
    event.preventDefault();
    const next = Math.min(fecs.length - 1, Math.max(0, (selectedIndex < 0 ? -1 : selectedIndex) + step));
    select(fecs[next].fecId);
    const element = listRef.current;
    if (element !== null) {
      const top = next * FEC_ROW_HEIGHT;
      if (top < element.scrollTop) {
        element.scrollTop = top;
      } else if (top + FEC_ROW_HEIGHT > element.scrollTop + element.clientHeight) {
        element.scrollTop = top + FEC_ROW_HEIGHT - element.clientHeight;
      }
    }
  };

  if (running !== null) {
    return (
      <div className="fec-browser fec-browser--empty">
        <EmptyState title="Exploring the design space">
          <LoadingSpinner label={running.message ?? "Waiting for the exploration job..."} size="sm" />
          {running.progress !== null ? <progress className="fec-progress" max={1} value={running.progress} aria-label="Share of the cap found" /> : null}
          <p className="meta">The FECs are listed here once the exploration ended.</p>
        </EmptyState>
      </div>
    );
  }
  if (campaignId === null) {
    return (
      <div className="fec-browser fec-browser--empty">
        <EmptyState title="No exploration yet">
          <p>
            This page finds the functional equivalence classes (FECs) of a design space: every model of the metamodel and the well-formedness constraints within the
            scope is one FEC, a complete specification the Scene Generation page can generate a scene of.
          </p>
          <p className="meta">Write or load the specification in the pane on the right, enter the scope below, then press Explore.</p>
        </EmptyState>
      </div>
    );
  }

  const summary = result !== null ? describeExploration(result, fecs.length) : `${fecs.length} FEC${fecs.length === 1 ? "" : "s"}.`;

  return (
    <div className="fec-browser">
      <div className="fec-browser-list">
        <p className="fec-summary" role="status">
          {summary}
        </p>
        {result?.message ? <p className="meta fec-summary-note">{result.message}</p> : null}
        {fecs.length === 0 ? (
          <EmptyState title="No FEC to list">
            <p className="meta">Change the specification or widen the scope, then explore again.</p>
          </EmptyState>
        ) : (
          <div
            ref={listRef}
            className="fec-list"
            role="listbox"
            aria-label="Explored FECs"
            aria-activedescendant={selected !== null ? `fec-row-${selected.index}` : undefined}
            tabIndex={0}
            onKeyDown={moveSelection}
            onScroll={(event) => {
              const top = event.currentTarget.scrollTop;
              setView((current) => (current.top === top ? current : { ...current, top }));
            }}
          >
            <div className="fec-list-space" style={{ height: fecs.length * FEC_ROW_HEIGHT }}>
              {fecs.slice(first, last).map((fec, offset) => {
                const text = texts[fec.fecId];
                const error = textErrors[fec.fecId];
                return (
                  <div
                    key={fec.fecId}
                    id={`fec-row-${fec.index}`}
                    role="option"
                    aria-selected={fec.fecId === selectedFecId}
                    className={`fec-row${fec.fecId === selectedFecId ? " is-selected" : ""}`}
                    style={{ top: (first + offset) * FEC_ROW_HEIGHT, height: FEC_ROW_HEIGHT }}
                    onClick={() => select(fec.fecId)}
                  >
                    <span className="fec-row-head">
                      <span className="fec-row-id">{fec.fecId}</span>
                      <span className="fec-row-counts">{fecCounts(fec)}</span>
                    </span>
                    <span className={`fec-row-relations${text === undefined ? " is-pending" : ""}`} title={text !== undefined ? fecRelationSummary(text) : error}>
                      {text !== undefined ? fecRelationSummary(text) : error !== undefined ? "text not readable" : "reading its relations..."}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
      <div className="fec-browser-detail">
        {selected === null ? (
          <EmptyState title="No FEC selected">
            <p className="meta">Select a FEC in the list to read its whole specification.</p>
          </EmptyState>
        ) : (
          <>
            <div className="fec-detail-head">
              <h4 className="fec-detail-title">
                {selected.fecId} <span className="meta">{fecCounts(selected)}</span>
              </h4>
              <ViewSwitch label="Show the FEC as" value={detailView} onChange={setDetailView} order={["graph", "text"]} />
            </div>
            {texts[selected.fecId] !== undefined ? (
              detailView === "graph" ? (
                <ModelGraph text={texts[selected.fecId]} label={`Model graph of ${selected.fecId}`} />
              ) : (
                <ProblemEditor value={texts[selected.fecId]} readOnly ariaLabel={`Specification of ${selected.fecId}`} />
              )
            ) : textErrors[selected.fecId] !== undefined ? (
              <p className="error">{textErrors[selected.fecId]}</p>
            ) : (
              <LoadingSpinner label="Reading the FEC's text..." size="sm" />
            )}
          </>
        )}
      </div>
    </div>
  );
}
