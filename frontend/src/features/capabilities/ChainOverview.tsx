import { Fragment } from "react";
import { useShallow } from "zustand/react/shallow";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useWorkerNodesFeed, useWorkerNodesStore } from "../../domain/cluster/workerNodesStore";
import type { ArchitectureDocument } from "../../domain/cluster/architectureApi";
import { capabilityLabel } from "../campaigns/resourcePlan";
import { jobTypeResources, type WorkerNodesFeedState } from "../workbench/cluster/workbenchResources";
import { chainOf, describePartOffer, partCounts, type ChainPart, type JobOffer, type PartOffer } from "./capabilitiesModel";

/** A simulation's components depend on its stack, so the overview counts the machines with simulation slots. */
const ANY_COMPONENTS: readonly string[] = [];

function offersOf(feed: WorkerNodesFeedState, document: ArchitectureDocument): JobOffer[] {
  return document.job_types.map((jobType) => {
    const resources = jobType === "simulation" ? jobTypeResources(feed, jobType, ANY_COMPONENTS) : jobTypeResources(feed, jobType);
    return { jobType, machines: resources.workerNodes, slots: resources.slots };
  });
}

function usePartOffers(documents: readonly ArchitectureDocument[]): Map<string, PartOffer> {
  const cluster = useSelectedCluster();
  const operatorUrl = cluster?.operatorUrl ?? null;
  useWorkerNodesFeed(operatorUrl);
  const feed = useWorkerNodesStore(useShallow((state) => ({ operatorUrl: state.operatorUrl, workerNodes: state.workerNodes, loaded: state.loaded, unreachable: state.unreachable })));
  // The store may still hold another cluster's machines right after the selection changed
  const current = feed.operatorUrl === operatorUrl;
  const state = { selected: operatorUrl !== null, loaded: current && feed.loaded, unreachable: current && feed.unreachable };
  return new Map(documents.map((document) => [document.id, describePartOffer(state, current ? offersOf(feed, document) : [])]));
}

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

interface PartCardProps {
  part: ChainPart;
  offer: PartOffer;
  onOpen: (documentId: string) => void;
}

function PartCard({ part, offer, onOpen }: PartCardProps) {
  const { document } = part;
  const counts = partCounts(document);
  const titleId = `cap-part-${document.id}`;
  return (
    <article className={`cap-part${part.number === null ? " cap-part--support" : ""}`} aria-labelledby={titleId}>
      <header className="cap-part-head">
        {part.number !== null && (
          <span className="cap-part-number" aria-hidden="true">
            {part.number}
          </span>
        )}
        <div className="cap-part-names">
          <h3 id={titleId} className="cap-part-title">
            {part.name}
          </h3>
          {part.partName !== null && <p className="cap-part-sub">done by the {part.partName.toLowerCase()}</p>}
        </div>
      </header>
      <p className="cap-part-summary">{document.summary}</p>
      <dl className="cap-part-facts">
        {document.takes !== "" && (
          <div>
            <dt>Takes</dt>
            <dd>{document.takes}</dd>
          </div>
        )}
        {document.gives !== "" && (
          <div>
            <dt>Gives</dt>
            <dd>{document.gives}</dd>
          </div>
        )}
        {document.job_types.length > 0 && (
          <div>
            <dt>Runs as</dt>
            <dd>{document.job_types.map((jobType) => `the ${capabilityLabel(jobType).toLowerCase()} job`).join(", ")}</dd>
          </div>
        )}
        <div>
          <dt>On this cluster</dt>
          <dd className={`cap-part-offer cap-part-offer--${offer.tone}`}>{offer.text}</dd>
        </div>
        <div>
          <dt>Described</dt>
          <dd>
            {plural(counts.implementations, "implementation")}
            {counts.measured > 0 ? `, ${plural(counts.measured, "measured value")}` : ", nothing measured yet"}
          </dd>
        </div>
      </dl>
      <button type="button" className="cap-part-open" aria-label={`Open ${document.title.toLowerCase()}`} onClick={() => onOpen(document.id)}>
        Open
      </button>
    </article>
  );
}

interface Props {
  documents: readonly ArchitectureDocument[];
  onOpen: (documentId: string) => void;
}

/**
 * The page's first view: the chain from a specification to judged runs, one card per part in the order the
 * control node lists them, with what each takes and gives, the job that runs it and whether the selected cluster
 * offers it now. Everything on the cards comes from the control node's documents and the cluster's machines.
 */
export function ChainOverview({ documents, onOpen }: Props) {
  const chain = chainOf(documents);
  const offers = usePartOffers(documents);
  const offerOf = (part: ChainPart) => offers.get(part.document.id) ?? describePartOffer({ selected: false, loaded: false, unreachable: false }, []);
  return (
    <div className="cap-overview">
      <section aria-labelledby="cap-chain-title">
        <h2 id="cap-chain-title" className="cap-overview-title">
          {chain.described ? "The chain" : "The parts"}
        </h2>
        <p className="cap-overview-lead">
          {chain.described
            ? "A scenario is made and run in steps. Each step is one part of the system: it takes what the step before gives. Open a part to see what implements it, what was measured, and what a new implementation has to provide."
            : "The parts of the system, as this control node describes them. Open a part to see what implements it, what was measured, and what a new implementation has to provide."}
        </p>
        <ol className={`cap-chain${chain.described ? "" : " cap-chain--plain"}`}>
          {chain.steps.map((part, index) => (
            <Fragment key={part.document.id}>
              {index > 0 && chain.described && (
                <li className="cap-chain-link" aria-hidden="true">
                  <span className="cap-chain-arrow" />
                  {chain.steps[index - 1].document.gives !== "" && <span className="cap-chain-carries">{chain.steps[index - 1].document.gives}</span>}
                </li>
              )}
              <li className="cap-chain-step">
                <PartCard part={chain.described ? part : { ...part, number: null }} offer={offerOf(part)} onOpen={onOpen} />
              </li>
            </Fragment>
          ))}
        </ol>
      </section>
      {chain.support.length > 0 && (
        <section aria-labelledby="cap-support-title">
          <h2 id="cap-support-title" className="cap-overview-title">
            Alongside every step
          </h2>
          <div className="cap-support">
            {chain.support.map((part) => (
              <PartCard key={part.document.id} part={part} offer={offerOf(part)} onOpen={onOpen} />
            ))}
          </div>
        </section>
      )}
      <section aria-labelledby="cap-reading-title" className="cap-reading">
        <h2 id="cap-reading-title" className="cap-overview-title">
          How a part is shown
        </h2>
        <dl className="cap-reading-list">
          <div>
            <dt>Implemented</dt>
            <dd>What exists now: every implementation as a card, and the adapters or data that connect them. Click a card or an arrow for its values.</dd>
          </div>
          <div>
            <dt>Metamodel</dt>
            <dd>The generic structure behind the implementations: what a new one has to provide, and where it is defined in the code.</dd>
          </div>
          <div>
            <dt>Matrix</dt>
            <dd>For the vessel stack: every combination of its three layers, whether it exists and what it allows.</dd>
          </div>
          <div>
            <dt>Measured</dt>
            <dd>A value with a dot was measured, with the evidence beside it. Every other value is declared in the code.</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
