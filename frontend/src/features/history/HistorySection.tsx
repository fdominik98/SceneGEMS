import "../campaigns/campaigns.css";
import "./history.css";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { useUiStore } from "../../app/uiStore";
import { EmptyState } from "./campaignParts";
import { EntryDetail } from "./EntryDetail";
import { HistoryList } from "./HistoryList";
import { selectOpenEntry, useHistoryStore } from "./historyStore";

/**
 * Campaign History of the selected cluster: every entry (campaigns and workbench runs, ongoing
 * and finished) and one entry's page with its steps and outputs. Replaces the Observe section;
 * the per-worker-node instance browser is on the Cluster page.
 */
export function HistorySection() {
  const cluster = useSelectedCluster();
  const clusterId = cluster?.id ?? null;
  const entryId = useHistoryStore((state) => selectOpenEntry(state, clusterId));
  const step = useHistoryStore((state) => state.step);
  const openEntry = useHistoryStore((state) => state.openEntry);
  const closeEntry = useHistoryStore((state) => state.closeEntry);
  const setStep = useHistoryStore((state) => state.setStep);
  const setSection = useUiStore((state) => state.setSection);

  const open = (campaignId: string) => openEntry(clusterId, campaignId);

  let content;
  if (!cluster) {
    content = (
      <EmptyState title="No cluster selected">
        <p className="meta">Add a cluster or select one in the Cluster section to see its campaigns and workbench runs.</p>
      </EmptyState>
    );
  } else if (entryId) {
    content = <EntryDetail key={`${cluster.id}/${entryId}`} campaignId={entryId} step={step} onStep={setStep} onBack={closeEntry} onOpenEntry={open} />;
  } else {
    content = <HistoryList onOpen={open} clusterName={cluster.name} operatorUrl={cluster.operatorUrl} />;
  }

  const actions =
    cluster && !entryId ? (
      <button type="button" className="primary-btn accent" onClick={() => setSection("campaigns")}>
        New campaign
      </button>
    ) : undefined;

  return (
    <SectionFrame title="Campaign History" subtitle="Every campaign and workbench run of the selected cluster, its steps and outputs." actions={actions}>
      {content}
    </SectionFrame>
  );
}
