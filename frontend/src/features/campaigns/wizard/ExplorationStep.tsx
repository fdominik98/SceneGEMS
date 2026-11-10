import { useCallback } from "react";
import { SCOPE_FORM } from "../../../domain/designSpace/designSpaceScope";
import { DesignSpaceSpecificationEditor } from "../../workbench/designSpace/DesignSpaceSpecificationEditor";
import { editedLabel } from "../../workbench/designSpace/explorationInputStore";
import { ScopeInput } from "../../workbench/designSpace/ScopeInput";
import { FailureBudgetField, Field, FieldIssues, NumberField } from "./fields";
import { reasonsOfEntry, splitByField, type Reason } from "./reasons";
import type { StepProps } from "./stepTypes";

const FIELDS = ["specification", "scope", "max_fecs", "timeout_s", "quota", "failure_budget"];

/** The master's reasons only: the browser's own scope check shows under the field as it is typed. */
function serverOnly(reasons: readonly Reason[] | undefined): Reason[] | undefined {
  return reasons?.filter((reason) => reason.source === "server");
}

/**
 * Design space exploration: the specification (the metamodel and the well-formedness constraints),
 * the scope, the search's limits and, when later steps run, what each explored FEC needs. Written to
 * the config's `design_space_exploration` section; the campaign then takes no input of its own.
 */
export function ExplorationStep({ draft, update, reasons }: StepProps) {
  const { exploration } = draft;
  const own = splitByField(reasonsOfEntry(reasons, null), FIELDS);
  const laterSteps = draft.steps.length > 1;
  const onLoad = useCallback(
    (text: string, label: string) =>
      update((next) => {
        next.exploration.specification = text;
        next.exploration.specificationLabel = label;
      }),
    [update]
  );
  const onDefaultScope = useCallback(
    (scope: string) =>
      update((next) => {
        if (next.exploration.scope.trim().length === 0) {
          next.exploration.scope = scope;
        }
      }),
    [update]
  );

  return (
    <div className="wiz-step">
      <p className="meta wiz-explain">
        The design space exploration enumerates every model of the specification within the scope. Each model is one functional equivalence class (FEC), a
        complete FEC specification; {laterSteps ? "the later steps run cases of every FEC it finds." : "the campaign ends with the list of FECs."} How many FECs
        there are is known only once the exploration ran.
      </p>
      <Field
        label="Metamodel and well-formedness constraints"
        hint="The first part of a FEC specification: classes, relations, error constraints and the lines that pin the own ship."
        issues={own.byField.get("specification")}
      >
        <div className="wiz-exploration-editor">
          <DesignSpaceSpecificationEditor
            value={exploration.specification}
            label={exploration.specificationLabel}
            onEdit={(text) =>
              update((next) => {
                next.exploration.specification = text;
                next.exploration.specificationLabel = editedLabel(next.exploration.specificationLabel);
              })
            }
            onLoad={onLoad}
            onDefaultScope={onDefaultScope}
            autoLoadDefault
            exportName="design_space.problem"
          />
        </div>
      </Field>
      <Field label="Scope" htmlFor="wiz-exploration-scope" hint={`How many objects of each class a model has: ${SCOPE_FORM}.`} issues={serverOnly(own.byField.get("scope"))}>
        <ScopeInput id="wiz-exploration-scope" value={exploration.scope} onChange={(scope) => update((next) => void (next.exploration.scope = scope))} />
      </Field>
      <div className="wiz-row">
        <Field label="Max FECs" htmlFor="wiz-exploration-max" hint="The search stops after this many; empty finds every FEC." issues={own.byField.get("max_fecs")}>
          <NumberField
            id="wiz-exploration-max"
            integer
            min={1}
            placeholder="every"
            value={exploration.maxFecs}
            invalid={own.byField.has("max_fecs")}
            onChange={(value) => update((next) => void (next.exploration.maxFecs = value))}
          />
        </Field>
        <Field label="Timeout" htmlFor="wiz-exploration-timeout" hint="How long the search may run; the FECs found until then are kept." issues={own.byField.get("timeout_s")}>
          <NumberField
            id="wiz-exploration-timeout"
            integer
            min={1}
            suffix="s"
            value={exploration.timeoutS}
            invalid={own.byField.has("timeout_s")}
            onChange={(value) => update((next) => void (next.exploration.timeoutS = value))}
          />
        </Field>
      </div>
      {laterSteps ? (
        <div className="wiz-row">
          <Field label="Cases per explored FEC" htmlFor="wiz-exploration-quota" hint="Complete cases every FEC the exploration finds needs." issues={own.byField.get("quota")}>
            <NumberField
              id="wiz-exploration-quota"
              integer
              min={1}
              value={exploration.quota}
              invalid={own.byField.has("quota")}
              onChange={(value) => update((next) => void (next.exploration.quota = value))}
            />
          </Field>
          <Field
            label="Failure budget per explored FEC"
            htmlFor="wiz-exploration-budget"
            hint="Dropped and failed cases a FEC may use up before it is abandoned."
            issues={own.byField.get("failure_budget")}
          >
            <FailureBudgetField
              id="wiz-exploration-budget"
              value={exploration.failureBudget}
              invalid={own.byField.has("failure_budget")}
              onChange={(value) => update((next) => void (next.exploration.failureBudget = value))}
            />
          </Field>
        </div>
      ) : (
        <p className="meta wiz-explain">The campaign runs the exploration alone, so its FECs need no cases.</p>
      )}
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
