import type { ReactNode } from "react";
import { Disclosure } from "../../components/Disclosure";
import type { ArchitectureDocument, Fact } from "../../domain/cluster/architectureApi";
import type { Selection } from "./ArchitectureGraph";
import { CLUSTER_JOB_FACT, factsByGroup, factTone, formatFactValue, shortId, stacksRunAsJobs, stacksThrough, words, type GraphView } from "./capabilitiesModel";

interface DetailPanelProps {
  document: ArchitectureDocument;
  view: GraphView;
  selection: Selection | null;
  /** Show another item, possibly in the other graph. */
  onShow: (view: GraphView, selection: Selection | null) => void;
}

const GROUP_TITLES = { capability: "Capabilities", parameter: "Parameters", property: "Properties" } as const;
/** The facts a stack of the list shows as chips, with their labels. */
const STACK_CHIP_LABELS: Record<string, string> = { [CLUSTER_JOB_FACT]: "Job", repeatability_tier: "Repeat", max_speedup: "Speedup" };

function FactRows({ facts }: { facts: readonly Fact[] }) {
  const groups = factsByGroup(facts);
  return (
    <>
      {(Object.keys(GROUP_TITLES) as Array<keyof typeof GROUP_TITLES>).map((group) =>
        groups[group].length === 0 ? null : (
          <section key={group} className="cap-detail-section">
            <h4 className="cap-detail-heading">{GROUP_TITLES[group]}</h4>
            <dl className="cap-facts">
              {groups[group].map((fact) => (
                <div key={fact.key} className="cap-fact">
                  <dt>{fact.label}</dt>
                  <dd>
                    <span className={`cap-fact-value cap-fact-value--${factTone(fact)}`}>{formatFactValue(fact)}</span>
                    {group === "capability" && <span className={`cap-fact-source${fact.measured ? " is-measured" : ""}`}>{fact.measured ? "measured" : "declared"}</span>}
                    {fact.note && <span className="cap-fact-note">{fact.note}</span>}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        )
      )}
    </>
  );
}

function PortList({ provided, required }: { provided: readonly string[]; required: readonly string[] }) {
  if (provided.length === 0 && required.length === 0) {
    return null;
  }
  return (
    <section className="cap-detail-section">
      <h4 className="cap-detail-heading">Ports</h4>
      <dl className="cap-facts">
        {provided.length > 0 && (
          <div className="cap-fact">
            <dt>Provides</dt>
            <dd>{provided.map(words).join(", ")}</dd>
          </div>
        )}
        {required.length > 0 && (
          <div className="cap-fact">
            <dt>Requires</dt>
            <dd>{required.map(words).join(", ")}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

function Evidence({ id, text }: { id: string; text: string }) {
  if (text === "") {
    return null;
  }
  return (
    <Disclosure id={`capabilities:evidence:${id}`} variant="plain" headingLevel={4} title="How it was measured">
      <p className="cap-evidence">{text}</p>
    </Disclosure>
  );
}

function Header({ eyebrow, title, badges, children }: { eyebrow: string; title: string; badges?: ReactNode; children?: ReactNode }) {
  return (
    <header className="cap-detail-header">
      <p className="cap-detail-eyebrow">{eyebrow}</p>
      <h3 className="cap-detail-title">{title}</h3>
      {badges && <div className="cap-detail-badges">{badges}</div>}
      {children && <p className="cap-detail-text">{children}</p>}
    </header>
  );
}

function Members({ title, items }: { title: string; items: readonly string[] }) {
  if (items.length === 0) {
    return null;
  }
  return (
    <section className="cap-detail-section">
      <h4 className="cap-detail-heading">{title}</h4>
      <ul className="cap-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

/** The right-hand panel: what the selected card or arrow is, its values and where they come from; the whole document when nothing is selected. */
export function DetailPanel({ document, view, selection, onShow }: DetailPanelProps) {
  const nodeLabel = (id: string) => document.nodes.find((node) => node.id === id)?.label ?? document.metamodel_nodes.find((node) => node.id === id)?.label ?? shortId(id);
  let body: ReactNode;

  if (selection === null) {
    body = <Overview document={document} view={view} />;
  } else if (selection.id.startsWith("ruled-out:")) {
    const link = document.unsupported.find((item) => `ruled-out:${item.source}>${item.target}` === selection.id);
    body = (
      <>
        <Header eyebrow="Ruled out" title={link ? `${words(nodeLabel(link.source))} to ${words(nodeLabel(link.target))}` : "Ruled out"} badges={<span className="cap-tag cap-tag--bad">no adapter</span>}>
          {link?.reason}
        </Header>
        <p className="cap-detail-text">The design rules this connection out, so a stack that needs it is unavailable.</p>
      </>
    );
  } else if (view === "concrete" && selection.kind === "node") {
    const node = document.nodes.find((item) => item.id === selection.id);
    const meta = document.metamodel_nodes.find((item) => item.id === node?.implements);
    const stacks = stacksThrough(document, selection.id);
    body = node ? (
      <>
        <Header
          eyebrow={document.lanes.find((lane) => lane.id === node.lane)?.label ?? node.lane}
          title={words(node.label)}
          badges={
            <>
              {node.status === "planned" && <span className="cap-tag cap-tag--planned">planned</span>}
              {node.tags.map((tag) => (
                <span key={tag} className="cap-tag">
                  {tag}
                </span>
              ))}
            </>
          }
        >
          {node.description}
        </Header>
        {meta && (
          <button type="button" className="cap-link" onClick={() => onShow("metamodel", { kind: "node", id: meta.id })}>
            Implements {meta.label}: show what it must provide
          </button>
        )}
        <FactRows facts={node.facts} />
        <PortList provided={node.ports_provided} required={node.ports_required} />
        <Evidence id={node.id} text={node.evidence} />
        {document.combinations.length > 0 && <Stacks stacks={stacks} />}
      </>
    ) : null;
  } else if (view === "concrete") {
    const edge = document.edges.find((item) => item.id === selection.id);
    const meta = document.metamodel_edges.find((item) => item.id === edge?.implements);
    body = edge ? (
      <>
        <Header
          eyebrow={edge.kind === "adapter" ? "Adapter" : edge.kind === "data" ? "Data flow" : "Uses"}
          title={words(edge.label)}
          badges={
            <>
              <span className="cap-tag">
                {words(nodeLabel(edge.source))} to {words(nodeLabel(edge.target))}
              </span>
              {!edge.default && <span className="cap-tag">alternative</span>}
              {edge.status === "planned" && <span className="cap-tag cap-tag--planned">planned</span>}
              {edge.tags
                .filter((tag) => tag !== "alternative")
                .map((tag) => (
                  <span key={tag} className="cap-tag">
                    {tag}
                  </span>
                ))}
            </>
          }
        >
          {edge.description}
        </Header>
        {meta && (
          <button type="button" className="cap-link" onClick={() => onShow("metamodel", { kind: "edge", id: meta.id })}>
            Implements {meta.label}: show what it must provide
          </button>
        )}
        <FactRows facts={edge.facts} />
        <PortList provided={edge.ports_provided} required={edge.ports_required} />
        <Evidence id={edge.id} text={edge.evidence} />
      </>
    ) : null;
  } else if (selection.kind === "node") {
    const node = document.metamodel_nodes.find((item) => item.id === selection.id);
    const implementations = document.nodes.filter((item) => item.implements === selection.id);
    body = node ? (
      <>
        <Header eyebrow={document.lanes.find((lane) => lane.id === node.lane)?.label ?? node.lane} title={node.label} badges={<span className="cap-tag cap-tag--kind">{node.kind}</span>}>
          {node.description}
        </Header>
        <Members title="An implementation provides" items={node.members} />
        {node.extension && (
          <section className="cap-detail-section">
            <h4 className="cap-detail-heading">To add one</h4>
            <p className="cap-detail-text">{node.extension}</p>
          </section>
        )}
        {node.code && (
          <section className="cap-detail-section">
            <h4 className="cap-detail-heading">Defined in</h4>
            <code className="cap-code">{node.code}</code>
          </section>
        )}
        <Implementations items={implementations.map((item) => ({ id: item.id, label: words(item.label), kind: "node" as const }))} onShow={onShow} />
      </>
    ) : null;
  } else {
    const edge = document.metamodel_edges.find((item) => item.id === selection.id);
    const implementations = document.edges.filter((item) => item.implements === selection.id);
    body = edge ? (
      <>
        <Header
          eyebrow={edge.kind === "adapter" ? "Generic adapter" : edge.kind === "data" ? "Data flow" : "Uses"}
          title={edge.label}
          badges={
            <span className="cap-tag">
              {nodeLabel(edge.source)} to {nodeLabel(edge.target)}
            </span>
          }
        >
          {edge.description}
        </Header>
        <Members title="An adapter provides" items={edge.members} />
        {edge.extension && (
          <section className="cap-detail-section">
            <h4 className="cap-detail-heading">To add one</h4>
            <p className="cap-detail-text">{edge.extension}</p>
          </section>
        )}
        {edge.code && (
          <section className="cap-detail-section">
            <h4 className="cap-detail-heading">Defined in</h4>
            <code className="cap-code">{edge.code}</code>
          </section>
        )}
        <Implementations items={implementations.map((item) => ({ id: item.id, label: words(item.label), kind: "edge" as const }))} onShow={onShow} />
      </>
    ) : null;
  }

  return (
    <aside className="cap-detail" aria-label="Details">
      {selection !== null && (
        <button type="button" className="cap-link cap-detail-clear" onClick={() => onShow(view, null)}>
          Back to the overview
        </button>
      )}
      {body}
    </aside>
  );
}

function Implementations({ items, onShow }: { items: Array<{ id: string; label: string; kind: "node" | "edge" }>; onShow: DetailPanelProps["onShow"] }) {
  return (
    <section className="cap-detail-section">
      <h4 className="cap-detail-heading">Implemented by</h4>
      {items.length === 0 ? (
        <p className="cap-detail-text">Nothing yet.</p>
      ) : (
        <ul className="cap-list cap-list--buttons">
          {items.map((item) => (
            <li key={item.id}>
              <button type="button" className="cap-link" onClick={() => onShow("concrete", { kind: item.kind, id: item.id })}>
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Stacks({ stacks }: { stacks: ArchitectureDocument["combinations"] }) {
  return (
    <section className="cap-detail-section">
      <h4 className="cap-detail-heading">Available stacks through it ({stacks.length})</h4>
      {stacks.length === 0 ? (
        <p className="cap-detail-text">No stack uses it yet.</p>
      ) : (
        <ul className="cap-stacks">
          {stacks.map((stack) => {
            const chips = stack.facts.filter((fact) => fact.key in STACK_CHIP_LABELS);
            return (
              <li key={stack.path.join(">")} className="cap-stack">
                <span className="cap-stack-path">{stack.path.map(shortId).map(words).join(" · ")}</span>
                <span className="cap-stack-facts">
                  {chips.map((fact) => (
                    <span key={fact.key} className={`cap-chip cap-chip--${factTone(fact)}`} title={fact.note ?? undefined}>
                      <span className="cap-chip-label">{STACK_CHIP_LABELS[fact.key]}</span>
                      <span className="cap-chip-value">{fact.value === null ? (fact.key === CLUSTER_JOB_FACT ? "none" : "?") : formatFactValue(fact)}</span>
                    </span>
                  ))}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Overview({ document, view }: { document: ArchitectureDocument; view: GraphView }) {
  const measured = [...document.nodes, ...document.edges].reduce((sum, item) => sum + item.facts.filter((fact) => fact.measured).length, 0);
  const available = document.combinations.filter((combination) => combination.status === "available").length;
  const runAsJobs = stacksRunAsJobs(document);
  return (
    <>
      <Header eyebrow={view === "concrete" ? "Implemented now" : "Metamodel"} title={document.title}>
        {document.summary}
      </Header>
      <dl className="cap-facts">
        <div className="cap-fact">
          <dt>{view === "concrete" ? "Implementations" : "Generic nodes"}</dt>
          <dd>{view === "concrete" ? document.nodes.length : document.metamodel_nodes.length}</dd>
        </div>
        <div className="cap-fact">
          <dt>{view === "concrete" ? "Adapters and links" : "Generic adapters and links"}</dt>
          <dd>{view === "concrete" ? document.edges.length : document.metamodel_edges.length}</dd>
        </div>
        {document.combinations.length > 0 && (
          <div className="cap-fact">
            <dt>Stacks that exist</dt>
            <dd>
              {available} of {document.combinations.length}
            </dd>
          </div>
        )}
        {runAsJobs !== null && (
          <div className="cap-fact">
            <dt>Run as cluster jobs</dt>
            <dd>
              {runAsJobs} of {available}
            </dd>
          </div>
        )}
        <div className="cap-fact">
          <dt>Measured values</dt>
          <dd>{measured}</dd>
        </div>
      </dl>
      <p className="cap-detail-text">{view === "concrete" ? "Click a card to see its values and the stacks it is part of. Click an arrow to see what the adapter carries." : "Click a card or arrow to see what an implementation has to provide and how to add one."}</p>
      {document.notes.map((note) => (
        <p key={note} className="cap-detail-note">
          {note}
        </p>
      ))}
    </>
  );
}
