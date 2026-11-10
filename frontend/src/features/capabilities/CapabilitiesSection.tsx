import { useRef, useState } from "react";
import "./capabilities.css";
import { usePersistedState } from "../../app/usePersistedState";
import { EmptyState } from "../../components/EmptyState";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { SectionFrame } from "../../components/SectionFrame";
import type { ArchitectureDocument } from "../../domain/cluster/architectureApi";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { ArchitectureGraph, type Selection } from "./ArchitectureGraph";
import { OVERVIEW_ID, type DocumentView, type GraphView } from "./capabilitiesModel";
import { ChainOverview } from "./ChainOverview";
import { DetailPanel } from "./DetailPanel";
import { MatrixView } from "./MatrixView";
import { useArchitecture } from "./useArchitecture";
import { useFullscreen } from "./useFullscreen";

const VIEW_LABELS: Record<DocumentView, string> = { concrete: "Implemented", metamodel: "Metamodel", matrix: "Matrix" };
const VIEW_HINTS: Record<DocumentView, string> = {
  concrete: "What exists now and what connects the parts. Click a card or an arrow for its values.",
  metamodel: "The generic structure a new implementation has to fill in. Click a card or an arrow for what it must provide.",
  matrix: "Every combination of the layers, whether it exists and what it allows.",
};

interface Stored {
  /** The shown tab: the overview, or a document's id. */
  documentId: string;
  views: Record<string, DocumentView>;
  showRuledOut: boolean;
}

/** A browser that has not chosen a tab yet starts on the overview. */
const DEFAULT_STORED: Stored = { documentId: OVERVIEW_ID, views: {}, showRuledOut: false };

/** A selection belongs to one view of one document and is gone when either changes. */
interface Selected {
  scope: string;
  selection: Selection | null;
}

function viewsOf(document: ArchitectureDocument): DocumentView[] {
  return document.combinations.length > 0 ? ["concrete", "metamodel", "matrix"] : ["concrete", "metamodel"];
}

/**
 * The Capabilities page. It opens on the overview: the chain from a specification to judged runs, one card per part
 * of the system, with what each takes and gives and whether the selected cluster offers it. Each part has a tab of its
 * own, drawn as a graph of what is implemented, with the adapters between the parts and the measured values, and as a
 * graph of the metamodel the implementations fill in. The documents come from the control node, which builds them from the
 * specs in code, so a new simulator, generator or step shows up without a change here.
 */
export function CapabilitiesSection() {
  const cluster = useSelectedCluster();
  const query = useArchitecture();
  const [stored, setStored] = usePersistedState<Stored>("capabilities-view", DEFAULT_STORED);
  const [selected, setSelected] = useState<Selected>({ scope: "", selection: null });
  const workspace = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen(workspace);

  const documents = query.data?.documents ?? [];
  // A stored id that names no document (a part the control node no longer has) falls back to the overview
  const document = documents.find((item) => item.id === stored.documentId);
  const available = document ? viewsOf(document) : [];
  const chosen = document ? stored.views[document.id] : undefined;
  const view: DocumentView = chosen !== undefined && available.includes(chosen) ? chosen : "concrete";
  const scope = `${document?.id}:${view}`;
  const selection = selected.scope === scope ? selected.selection : null;

  const open = (documentId: string) => setStored((current) => ({ ...current, documentId }));
  const setView = (next: DocumentView) => {
    if (document) {
      setStored((current) => ({ ...current, views: { ...current.views, [document.id]: next } }));
    }
  };
  const select = (next: Selection | null) => setSelected({ scope, selection: next });
  /** Show an item, possibly in the other graph. */
  const show = (next: GraphView, target: Selection | null) => {
    setView(next);
    setSelected({ scope: `${document?.id}:${next}`, selection: target });
  };

  let content;
  if (!cluster) {
    content = (
      <EmptyState title="No cluster selected">
        <p className="meta">The architecture comes from a control node. Add a cluster or select one in the Cluster section.</p>
      </EmptyState>
    );
  } else if (query.isPending) {
    content = (
      <div className="cap-status" role="status">
        <LoadingSpinner /> Reading the architecture from {cluster.name}
      </div>
    );
  } else if (query.isError && !query.data) {
    const unreachable = query.error instanceof OperatorApiError && query.error.unreachable;
    content = (
      <EmptyState
        title={unreachable ? "The control node cannot be reached" : "The architecture could not be read"}
        tone="error"
        action={
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        }
      >
        <p className="meta">{describeOperatorError(query.error)}</p>
      </EmptyState>
    );
  } else if (documents.length === 0) {
    content = (
      <EmptyState title="Nothing described yet">
        <p className="meta">The control node returned no architecture documents.</p>
      </EmptyState>
    );
  } else {
    content = (
      <div className="cap-page">
        <div className="cap-toolbar">
          <div className="cap-tabs" role="tablist" aria-label="Part of the system">
            <button type="button" role="tab" aria-selected={document === undefined} className={`cap-tab${document === undefined ? " active" : ""}`} onClick={() => open(OVERVIEW_ID)}>
              Overview
            </button>
            {documents.map((item) => (
              <button key={item.id} type="button" role="tab" aria-selected={item.id === document?.id} className={`cap-tab${item.id === document?.id ? " active" : ""}`} onClick={() => open(item.id)}>
                {item.title}
              </button>
            ))}
          </div>
        </div>
        {query.isError && (
          <p className="meta warning" role="status">
            The architecture may be out of date: reading it again failed ({describeOperatorError(query.error)}).
          </p>
        )}
        {document === undefined ? (
          <ChainOverview documents={documents} onOpen={open} />
        ) : (
          <>
            <div className="cap-viewbar">
              <div className="cap-views" role="group" aria-label="View">
                {available.map((option) => (
                  <button key={option} type="button" aria-pressed={option === view} className={`cap-view${option === view ? " active" : ""}`} onClick={() => setView(option)}>
                    {VIEW_LABELS[option]}
                  </button>
                ))}
              </div>
              <p className="cap-view-hint">{VIEW_HINTS[view]}</p>
              {view === "concrete" && document.unsupported.length > 0 && (
                <label className="cap-toggle">
                  <input type="checkbox" checked={stored.showRuledOut} onChange={(event) => setStored((current) => ({ ...current, showRuledOut: event.target.checked }))} />
                  Show ruled-out connections
                </label>
              )}
            </div>
            {view === "matrix" ? (
              <>
                <p className="cap-summary">{document.summary}</p>
                <MatrixView document={document} />
              </>
            ) : (
              <div ref={workspace} className={`cap-workspace${fullscreen.mode !== "off" ? " is-fullscreen" : ""}`}>
                <ArchitectureGraph
                  document={document}
                  view={view}
                  selection={selection}
                  onSelect={select}
                  showRuledOut={stored.showRuledOut && view === "concrete"}
                  fullscreen={fullscreen.mode}
                  onToggleFullscreen={fullscreen.toggle}
                />
                <DetailPanel document={document} view={view} selection={selection} onShow={show} />
              </div>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <SectionFrame title="Capabilities" subtitle="How a scenario is made and run, what each part of the system can do today, and what was measured about it.">
      {content}
    </SectionFrame>
  );
}
