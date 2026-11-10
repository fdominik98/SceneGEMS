import { useState } from "react";
import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import { useClusterDomain } from "../../domain/useClusterDomain";
import { ConstraintsEditor } from "../../workbench/controls/constraintsEditor";
import { FieldIssues } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import type { StepProps } from "./stepTypes";

type TextKey = "colregsConstants" | "vesselTypes" | "obstacleTypes";

const TEXT_TABS: { key: TextKey; field: string; label: string; protectedRows?: string[] }[] = [
  { key: "colregsConstants", field: "colregs_constants", label: "COLREGS constants" },
  { key: "vesselTypes", field: "vessel_types", label: "Vessel types", protectedRows: ["UnspecifiedVesselType"] },
  { key: "obstacleTypes", field: "obstacle_types", label: "Obstacle types", protectedRows: ["UnspecifiedObstacleType"] },
];

/**
 * Domain: the cluster's domain configuration, or customized COLREGS constants, vessel types and obstacle types stored in
 * the campaign. The scene generation settings of the config's domain section are on the Scene generation page.
 */
export function DomainStep({ draft, update, reasons }: StepProps) {
  const [tab, setTab] = useState<TextKey>("colregsConstants");
  const [source, setSource] = useState<string | null>(null);
  const clusterDomain = useClusterDomain();
  const { domain } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), ["colregs_constants", "vessel_types", "obstacle_types"]);
  const loadError = clusterDomain.isError ? describeOperatorError(clusterDomain.error) : null;

  /** Starts the customized texts from the cluster's domain configuration. */
  const loadStart = () => {
    const current = clusterDomain.data;
    if (!current) {
      return;
    }
    update((next) => {
      next.domain.colregsConstants = current.colregs_constants;
      next.domain.vesselTypes = current.vessel_types;
      next.domain.obstacleTypes = current.obstacle_types;
    });
    setSource(current.saved ? "the cluster's domain configuration" : "the control node's default presets (the cluster has saved no domain configuration)");
  };

  const chooseCustom = (custom: boolean) => {
    update((next) => void (next.domain.custom = custom));
    if (custom && domain.colregsConstants.trim() === "" && domain.vesselTypes.trim() === "" && domain.obstacleTypes.trim() === "") {
      loadStart();
    }
  };

  const active = TEXT_TABS.find((entry) => entry.key === tab) ?? TEXT_TABS[0];

  return (
    <div className="wiz-step">
      <fieldset className="wiz-choice">
        <legend>Domain content</legend>
        <label className={`wiz-option${domain.custom ? "" : " wiz-option--on"}`}>
          <input type="radio" name="wiz-domain" checked={!domain.custom} onChange={() => chooseCustom(false)} />
          <span>
            <strong>Use the cluster's domain configuration</strong>
            <span className="wiz-hint">The three texts are left out of the config. The control node fills them from the cluster's domain configuration (the Domain Configuration page) when the campaign is created, and the campaign keeps what it filled in.</span>
          </span>
        </label>
        <label className={`wiz-option${domain.custom ? " wiz-option--on" : ""}`}>
          <input type="radio" name="wiz-domain" checked={domain.custom} onChange={() => chooseCustom(true)} />
          <span>
            <strong>Customize</strong>
            <span className="wiz-hint">Edit the COLREGS constants, vessel types and obstacle types for this campaign only, starting from the cluster's domain configuration.</span>
          </span>
        </label>
      </fieldset>

      {domain.custom && (
        <section className="wiz-card" aria-label="Customized domain content">
          <p className="wiz-notice wiz-explain" role="note">
            Customized content is stored in the campaign: it becomes part of the campaign's config and its hash, so every case of this campaign uses exactly these texts, whatever the cluster's domain configuration says later.
          </p>
          <div className="wiz-domain-bar">
            <div className="ce-tabs" role="tablist" aria-label="Domain files">
              {TEXT_TABS.map((entry) => {
                const issues = own.byField.get(entry.field);
                return (
                  <button key={entry.key} type="button" role="tab" aria-selected={tab === entry.key} className={`ce-tab${tab === entry.key ? " active" : ""}`} onClick={() => setTab(entry.key)}>
                    {entry.label}
                    {issues && issues.length > 0 && <span className="ce-tab-flag" title="This text has a problem">!</span>}
                  </button>
                );
              })}
            </div>
            <span className="wiz-domain-actions">
              {source && <span className="meta">Started from {source}.</span>}
              <button type="button" onClick={loadStart} disabled={!clusterDomain.data} title="Replace the three texts with the cluster's domain configuration">
                {clusterDomain.isPending ? "Loading..." : "Start again from the cluster's configuration"}
              </button>
            </span>
          </div>
          {loadError && <p className="error" role="alert">{loadError}</p>}
          <FieldIssues reasons={own.byField.get(active.field)} />
          <div className="wiz-editor" role="tabpanel" aria-label={active.label}>
            <ConstraintsEditor
              key={active.key}
              text={domain[active.key]}
              onTextChange={(text) => update((next) => void (next.domain[active.key] = text))}
              label={active.label}
              protectedRows={active.protectedRows}
              tableMinRows={active.protectedRows ? 1 : undefined}
            />
          </div>
        </section>
      )}

      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
