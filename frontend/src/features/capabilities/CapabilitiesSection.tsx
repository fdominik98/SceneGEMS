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
import type { DocumentView, GraphView } from "./capabilitiesModel";
import { DetailPanel } from "./DetailPanel";
import { MatrixView } from "./MatrixView";
import { useArchitecture } from "./useArchitecture";
import { useFullscreen } from "./useFullscreen";

const VIEW_LABELS: Record<DocumentView, string> = { concrete: "Implemented", metamodel: "Metamodel", matrix: "Matrix" };
const VIEW_HINTS: Record<DocumentView, string> = {
  concrete: "What exists now and the adapters between the parts",
  metamodel: "The generic layers and interfaces a new part has to fill in",
  matrix: "Every combination and what it allows",
};

interface Stored {
  documentId: string;
  views: Record<string, DocumentView>;
  showRuledOut: boolean;
}

const DEFAULT_STORED: Stored = { documentId: "vessel_stack", views: {}, showRuledOut: false };

/** A selection belongs to one view of one document and is gone when either changes. */
interface Selected {
  scope: string;
  selection: Selection | null;
}

function viewsOf(document: ArchitectureDocument): DocumentView[] {
  return document.combinations.length > 0 ? ["concrete", "metamodel", "matrix"] : ["concrete", "metamodel"];
}

/**
 * The Capabilities page: one panel per part of the system (the vessel stack and the trajectory generation, scene
 * generation and monitoring subsystems), each drawn as a graph of what is implemented, with the adapters between the
 * parts and the measured values, and as a graph of the metamodel the implementations fill in. The documents come from
 * the master, which builds them from the specs in code, so a new simulator or generator shows up without a change here.
 */
export function CapabilitiesSection() {
  const cluster = useSelectedCluster();
  const query = useArchitecture();
  const [stored, setStored] = usePersistedState<Stored>("capabilities-view", DEFAULT_STORED);
  const [selected, setSelected] = useState<Selected>({ scope: "", selection: null });
  const workspace = useRef<HTMLDivElement>(null);
  const fullscreen = useFullscreen(workspace);

  const documents = query.data?.documents ?? [];
  const document = documents.find((item) => item.id === stored.documentId) ?? documents[0];
  const available = document ? viewsOf(document) : [];
  const chosen = document ? stored.views[document.id] : undefined;
  const view: DocumentView = chosen !== undefined && available.includes(chosen) ? chosen : "concrete";
  const scope = `${document?.id}:${view}`;
  const selection = selected.scope === scope ? selected.selection : null;

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
        <p className="meta">The architecture comes from a master. Add a cluster or select one in the Cluster section.</p>
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
        title={unreachable ? "The master cannot be reached" : "The architecture could not be read"}
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
  } else if (!document) {
    content = (
      <EmptyState title="Nothing described yet">
        <p className="meta">The master returned no architecture documents.</p>
      </EmptyState>
    );
  } else {
    content = (
      <div className="cap-page">
        <div className="cap-toolbar">
          <div className="cap-tabs" role="tablist" aria-label="Part of the system">
            {documents.map((item) => (
              <button
                key={item.id}
                type="button"
                role="tab"
                aria-selected={item.id === document.id}
                className={`cap-tab${item.id === document.id ? " active" : ""}`}
                onClick={() => setStored((current) => ({ ...current, documentId: item.id }))}
              >
                {item.title}
              </button>
            ))}
          </div>
          <div className="cap-views" role="group" aria-label="View">
            {available.map((option) => (
              <button key={option} type="button" aria-pressed={option === view} className={`cap-view${option === view ? " active" : ""}`} title={VIEW_HINTS[option]} onClick={() => setView(option)}>
                {VIEW_LABELS[option]}
              </button>
            ))}
          </div>
          {view === "concrete" && document.unsupported.length > 0 && (
            <label className="cap-toggle">
              <input type="checkbox" checked={stored.showRuledOut} onChange={(event) => setStored((current) => ({ ...current, showRuledOut: event.target.checked }))} />
              Show ruled-out connections
            </label>
          )}
        </div>
        {query.isError && (
          <p className="meta warning" role="status">
            The architecture may be out of date: reading it again failed ({describeOperatorError(query.error)}).
          </p>
        )}
        <p className="cap-summary">{document.summary}</p>
        {view === "matrix" ? (
          <MatrixView document={document} />
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
      </div>
    );
  }

  return (
    <SectionFrame title="Capabilities" subtitle="What the system can run today, what was measured about it, and the generic structure new parts plug into.">
      {content}
    </SectionFrame>
  );
}
