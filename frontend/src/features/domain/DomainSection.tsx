import { EmptyState } from "../../components/EmptyState";
import { LoadingSpinner } from "../../components/LoadingSpinner";
import { saveBlob } from "../../components/saveBlob";
import { SectionFrame } from "../../components/SectionFrame";
import { useSelectedCluster } from "../../domain/cluster/clusterStore";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { DomainKey } from "../../domain/cluster/presetsApi";
import "./domain.css";
import { DomainConfigurationPanel } from "./DomainConfigurationPanel";
import { defaultTexts, sameTexts, useDomainDraftStore } from "./domainDraftStore";
import { textsOf, useClusterDomain, useDomainPresets, useSaveClusterDomain } from "./useClusterDomain";

const EXPORT_NAMES: Record<DomainKey, string> = {
  colregs_constants: "colregs_constants.yaml",
  vessel_types: "vessel_types.yaml",
  obstacle_types: "static_obstacle_types.yaml",
};

function exportText(content: string, fileName: string) {
  saveBlob(new Blob([content], { type: "text/yaml" }), fileName);
}

function formatSavedAt(iso: string | null): string {
  if (iso === null) {
    return "";
  }
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleString();
}

/**
 * The cluster's domain configuration: the COLREGS constants, vessel types and obstacle types every
 * workbench run and every campaign without its own domain content uses. It is global for the
 * cluster and kept on the master; edits stay a draft in this page until they are saved.
 */
export function DomainSection() {
  const cluster = useSelectedCluster();
  const query = useClusterDomain();
  const presets = useDomainPresets();
  const save = useSaveClusterDomain();
  const clusterUrl = cluster?.operatorUrl ?? "";
  const draft = useDomainDraftStore((s) => s.drafts[clusterUrl]);
  const setText = useDomainDraftStore((s) => s.setText);
  const setTexts = useDomainDraftStore((s) => s.setTexts);
  const discard = useDomainDraftStore((s) => s.discard);
  const discardSaved = useDomainDraftStore((s) => s.discardSaved);

  const saved = query.data ? textsOf(query.data) : null;
  const texts = draft ?? saved;
  const dirty = draft !== undefined && saved !== null && !sameTexts(draft, saved);
  const editable = query.data?.editable ?? false;
  const defaults = defaultTexts(presets.data);
  const saveError = save.error;

  const onTextChange = (key: DomainKey, text: string) => {
    if (saved !== null) {
      setText(clusterUrl, saved, key, text);
    }
  };

  const actions =
    cluster && query.data ? (
      <>
        <button
          type="button"
          className="primary-btn accent"
          disabled={!dirty || !editable || save.isPending}
          onClick={() => {
            if (draft) {
              // Edits typed while the save was on its way stay a draft
              save.mutate(draft, { onSuccess: () => discardSaved(clusterUrl, draft) });
            }
          }}
        >
          {save.isPending ? "Saving..." : "Save to the cluster"}
        </button>
        <button type="button" disabled={!dirty || save.isPending} onClick={() => discard(clusterUrl)}>
          Discard changes
        </button>
      </>
    ) : undefined;

  let content;
  if (!cluster) {
    content = (
      <EmptyState title="No cluster selected">
        <p className="meta">The domain configuration is kept by a master. Add a cluster or select one in the Cluster section.</p>
      </EmptyState>
    );
  } else if (query.isPending) {
    content = (
      <div className="domain-section-status" role="status">
        <LoadingSpinner /> Reading the domain configuration from {cluster.name}
      </div>
    );
  } else if (!query.data || texts === null) {
    const unreachable = query.error instanceof OperatorApiError && query.error.unreachable;
    content = (
      <EmptyState
        title={unreachable ? "The master cannot be reached" : "The domain configuration could not be read"}
        tone="error"
        action={
          <button type="button" onClick={() => void query.refetch()}>
            Try again
          </button>
        }
      >
        <p className="meta">{query.error ? describeOperatorError(query.error) : "The master answered without a domain configuration."}</p>
      </EmptyState>
    );
  } else {
    content = (
      <div className="domain-section">
        <div className="domain-section-bar">
          <p className="meta" role="status">
            {query.data.saved ? `Saved on the master: ${formatSavedAt(query.data.updated_at)}.` : "Not saved yet: the master's default presets apply."}
            {dirty ? " You have unsaved changes; runs use the saved configuration until you save." : ""}
          </p>
          <button
            type="button"
            disabled={defaults === null || sameTexts(texts, defaults)}
            title="Replace the three texts with the master's default presets (save to apply them)"
            onClick={() => defaults && setTexts(clusterUrl, defaults)}
          >
            Load the default presets
          </button>
        </div>
        {query.isError && (
          <p className="meta warning" role="status">
            The configuration may be out of date: reading it again failed ({describeOperatorError(query.error)}).
          </p>
        )}
        {!editable && (
          <p className="wiz-notice" role="note">
            This master runs without its database, so it keeps no domain configuration of its own: every run uses its default presets.
          </p>
        )}
        {presets.isError && <p className="error">The master's presets could not be read: {describeOperatorError(presets.error)}</p>}
        {saveError && (
          <div className="error" role="alert">
            <p>{saveError.message}</p>
            {saveError instanceof OperatorApiError && saveError.reasons.length > 0 && (
              <ul>
                {saveError.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <DomainConfigurationPanel
          texts={texts}
          presets={presets.data ?? null}
          onTextChange={onTextChange}
          onLoadFile={(key, file) => void file.text().then((text) => onTextChange(key, text))}
          onExport={(key) => exportText(texts[key], EXPORT_NAMES[key])}
        />
      </div>
    );
  }

  return (
    <SectionFrame
      title="Domain Configuration"
      subtitle="The collision rules (COLREGS constants), vessel types and obstacle types of the cluster. Every workbench run and every campaign without domain content of its own uses them."
      actions={actions}
    >
      {content}
    </SectionFrame>
  );
}
