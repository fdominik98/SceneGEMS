import { useCallback } from "react";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { ArtifactRef } from "../../../domain/cluster/schemas";
import { shortHash } from "../../cluster/clusterFormat";
import { FailureBudgetField, Field, FieldIssues, NumberField } from "./fields";
import { scenarioFromUpload, uploadNote } from "./inputItems";
import { reasonsOfEntry, splitByField, type Reason } from "./reasons";
import type { StepProps } from "./stepTypes";
import { UploadControl } from "./UploadControl";
import type { ScenarioFileDraft } from "./wizardState";

const SCENARIO_FIELDS = ["name", "quota", "failure_budget", "ref"] as const;

function ScenarioCard({
  scenario,
  index,
  reasons,
  now,
  onChange,
  onRemove,
}: {
  scenario: ScenarioFileDraft;
  index: number;
  reasons: readonly Reason[];
  now: number;
  onChange: (change: (scenario: ScenarioFileDraft) => void) => void;
  onRemove: () => void;
}) {
  const { byField, rest } = splitByField(reasons, SCENARIO_FIELDS);
  return (
    <section className={`wiz-card${reasons.length > 0 ? " wiz-card--invalid" : ""}`} aria-label={`Scenario file ${index + 1}`}>
      <header className="wiz-card-head">
        <h4>Scenario file {index + 1}</h4>
        <span className="meta" title={scenario.ref.sha256}>
          {scenario.fileName}, {scenario.ref.size_bytes ?? 0} bytes, {shortHash(scenario.ref.sha256, 10)}
        </span>
        <button type="button" className="wiz-remove" onClick={onRemove}>
          Remove file
        </button>
      </header>
      <div className="wiz-row">
        <Field label="Name" htmlFor={`scenario-name-${scenario.id}`} hint={`The FEC is scenario/${scenario.name.trim() || "name"}.`} issues={byField.get("name")}>
          <input id={`scenario-name-${scenario.id}`} type="text" value={scenario.name} maxLength={200} onChange={(event) => onChange((item) => void (item.name = event.target.value))} />
        </Field>
        <Field label="Quota" htmlFor={`scenario-quota-${scenario.id}`} hint="Complete cases the scenario needs." issues={byField.get("quota")}>
          <NumberField id={`scenario-quota-${scenario.id}`} integer min={1} value={scenario.quota} invalid={byField.has("quota")} onChange={(value) => onChange((item) => void (item.quota = value))} />
        </Field>
        <Field label="Failure budget" htmlFor={`scenario-budget-${scenario.id}`} hint="Dropped or failed cases it may use up." issues={byField.get("failure_budget")}>
          <FailureBudgetField id={`scenario-budget-${scenario.id}`} value={scenario.failureBudget} invalid={byField.has("failure_budget")} onChange={(value) => onChange((item) => void (item.failureBudget = value))} />
        </Field>
      </div>
      <p className="wiz-hint">{uploadNote(scenario.uploadedAt, now)}</p>
      <FieldIssues reasons={[...(byField.get("ref") ?? []), ...rest]} showField />
    </section>
  );
}

/** Scenario files for scene generation: each is uploaded to the master and becomes a class of its own with a quota and failure budget. */
export function ScenarioFiles({ draft, update, reasons, client, now }: StepProps & { client: OperatorClient | null; now: number }) {
  const scenarios = draft.input.scenarios;
  const onUploaded = useCallback(
    (fileName: string, ref: ArtifactRef) =>
      update((next) => {
        next.input.scenarios.push(scenarioFromUpload(fileName, ref, next.input.scenarios.map((scenario) => scenario.name.trim()), Date.now()));
      }),
    [update]
  );
  const change = (id: string, edit: (scenario: ScenarioFileDraft) => void) =>
    update((next) => {
      const found = next.input.scenarios.find((scenario) => scenario.id === id);
      if (found) {
        edit(found);
      }
    });
  const own = reasonsOfEntry(reasons, null).filter((reason) => reason.field === "functional_scenarios");

  return (
    <section className="wiz-subsection wiz-subsection--first" aria-label="Functional scenario files">
      <h4 className="wiz-subhead">Functional scenario files</h4>
      <p className="meta wiz-explain">
        Optional. A scenario file is a functional scenario you wrote yourself (a <code>.problem</code> file). Each one becomes an FEC of its own and is generated like an FEC of the catalog. Uploaded files are kept for 24 hours; a campaign created with them keeps them.
      </p>
      <UploadControl client={client} kind="functional_scenario" label="Add scenario files" accept=".problem,.txt,text/plain" onUploaded={onUploaded} />
      <FieldIssues reasons={own} />
      {scenarios.map((scenario, index) => (
        <ScenarioCard
          key={scenario.id}
          scenario={scenario}
          index={index}
          reasons={reasonsOfEntry(reasons, index, "scenario")}
          now={now}
          onChange={(edit) => change(scenario.id, edit)}
          onRemove={() => update((next) => void (next.input.scenarios = next.input.scenarios.filter((item) => item.id !== scenario.id)))}
        />
      ))}
    </section>
  );
}
