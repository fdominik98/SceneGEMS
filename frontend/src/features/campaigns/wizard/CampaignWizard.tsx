import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createCampaign } from "../../../domain/cluster/campaignApi";
import { useSelectedCluster } from "../../../domain/cluster/clusterStore";
import { useNodesFeed, useNodesStore } from "../../../domain/cluster/nodesStore";
import { describeOperatorError, OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { NodeView } from "../../../domain/cluster/schemas";
import { planResources, requiredCapabilities, slotsByJobType, startBlocker } from "../resourcePlan";
import { useCatalogClasses, useCatalogStacks, useOperatorClient } from "../useCampaignData";
import { buildCampaignConfig, configToYaml, requiredLabelsOf, type BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { DomainStep } from "./DomainStep";
import { PolicyStep } from "./PolicyStep";
import { reasonsByStep, type Reason } from "./reasons";
import { ResourcesStep } from "./ResourcesStep";
import { ReviewStep } from "./ReviewStep";
import { RunsStep } from "./RunsStep";
import { InputStep } from "./InputStep";
import { PresetBar } from "./PresetBar";
import { StepsStep } from "./StepsStep";
import { visibleWizardSteps } from "./stepPlan";
import type { CatalogState, ClusterResources, StepProps } from "./stepTypes";
import { TrajectoriesStep } from "./TrajectoriesStep";
import { useValidation, validationFromError } from "./useValidation";
import { useWizardStore, WIZARD_STEP_LABELS, type WizardStepId } from "./wizardState";
import "./wizard.css";

const AUTO_CHECK_DELAY_MS = 700;
/** How often the check of uploaded files' expiry looks at the clock. */
const CLOCK_MS = 60_000;
const EMPTY_BUILDER: BuilderCatalog = { stacks: [], generators: [] };
const NO_NODES: readonly NodeView[] = [];

export interface CampaignWizardProps {
  onClose: () => void;
  onCreated: (campaignId: string) => void;
}

function describeCreateFailure(error: unknown): string {
  if (error instanceof OperatorApiError && error.status === 422) {
    return "The master refused the config. The reasons are listed above.";
  }
  return `The campaign was not created: ${describeOperatorError(error)}`;
}

/**
 * The create wizard: the steps of the chain to run, their input, the domain, the trajectories and
 * runs (only when those steps are chosen), resources and policy, then a review that validates the
 * config on the master.
 */
export function CampaignWizard({ onClose, onCreated }: CampaignWizardProps) {
  const client = useOperatorClient();
  const storedStep = useWizardStore((state) => state.step);
  const draft = useWizardStore((state) => state.draft);
  const visited = useWizardStore((state) => state.visited);
  const setStep = useWizardStore((state) => state.setStep);
  const update = useWizardStore((state) => state.update);
  const replaceDraft = useWizardStore((state) => state.replaceDraft);
  const reset = useWizardStore((state) => state.reset);

  // The pages of the chosen steps; a stored page that the steps no longer include falls back to the first
  const pages = useMemo(() => visibleWizardSteps(draft.steps), [draft.steps]);
  const step: WizardStepId = pages.includes(storedStep) ? storedStep : "steps";

  const classes = useCatalogClasses();
  const stacks = useCatalogStacks();
  const catalogState: CatalogState = {
    classes: classes.data?.items,
    classesError: classes.error,
    classesLoading: classes.isLoading,
    stacks: stacks.data,
    stacksError: stacks.error,
    stacksLoading: stacks.isLoading,
    retry: () => {
      void classes.refetch();
      void stacks.refetch();
    },
  };

  // The cluster's nodes: what the campaign needs is checked against them, and full usage sizes its queues to their slots
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const nodesState = useNodesStore();
  const nodesLoaded = operatorUrl !== null && nodesState.operatorUrl === operatorUrl && nodesState.loaded;
  const nodes = nodesLoaded ? nodesState.nodes : NO_NODES;
  const labels = useMemo(() => requiredLabelsOf(draft), [draft]);
  // Kept by content: heartbeats replace the node list every few seconds, the slots rarely change
  const slotsKey = JSON.stringify(slotsByJobType(nodes, labels));
  const slots = useMemo(() => JSON.parse(slotsKey) as Record<string, number>, [slotsKey]);

  const builderCatalog = useMemo<BuilderCatalog>(
    () => (stacks.data ? { stacks: stacks.data.stacks, generators: stacks.data.trajectory_generators, slots: nodesLoaded ? slots : undefined } : EMPTY_BUILDER),
    [stacks.data, nodesLoaded, slots]
  );
  const config = useMemo(() => buildCampaignConfig(draft, builderCatalog), [draft, builderCatalog]);
  const yaml = useMemo(() => configToYaml(config), [config]);
  // Uploaded files expire 24 hours after the upload: the clock makes the check see it
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);
  const localReasons = useMemo(() => checkDraft(draft, stacks.data ? builderCatalog : null, now), [draft, builderCatalog, stacks.data, now]);

  const plan = useMemo(
    () => (nodesLoaded ? planResources(requiredCapabilities(config), nodes, { nodes: draft.resources.fullUsage ? null : draft.resources.nodes, labels }) : null),
    [nodesLoaded, config, nodes, draft.resources.fullUsage, draft.resources.nodes, labels]
  );
  const cluster: ClusterResources = {
    selected: operatorUrl !== null,
    loaded: nodesLoaded,
    error: nodesState.operatorUrl === operatorUrl ? nodesState.error : null,
    nodes,
    plan,
    slots,
    startBlocker: startBlocker(plan),
  };

  const { state: validation, check, adopt, reset: resetValidation } = useValidation(client);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  // A run without a stack takes the first one the master can run
  useEffect(() => {
    const first = stacks.data?.stacks.find((entry) => entry.available);
    if (first && draft.runs.some((run) => run.stackId === "")) {
      update((next) => {
        for (const run of next.runs) {
          if (run.stackId === "") {
            run.stackId = first.id;
          }
        }
      });
    }
  }, [stacks.data, draft.runs, update]);

  // On the review step the master checks the config as soon as it is complete and has stopped changing
  useEffect(() => {
    if (step !== "review" || localReasons.length > 0 || !client || validation.yaml === yaml) {
      return undefined;
    }
    const timer = setTimeout(() => void check(yaml), AUTO_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [step, localReasons.length, client, validation.yaml, yaml, check]);

  const creation = useMutation({
    mutationFn: ({ start, target }: { start: boolean; target: OperatorClient }) => createCampaign(target, yaml, { start, kind: "campaign", origin: "wizard" }),
    onSuccess: (campaign) => {
      reset();
      resetValidation();
      setCreateMessage(null);
      onCreated(campaign.campaign_id);
    },
    onError: (error) => {
      adopt(validationFromError(yaml, error));
      setCreateMessage(describeCreateFailure(error));
    },
  });

  const serverReasons: Reason[] = validation.reasons;
  const allReasons = useMemo(() => [...localReasons, ...serverReasons], [localReasons, serverReasons]);
  const byStep = useMemo(() => reasonsByStep(allReasons), [allReasons]);
  // What the browser finds wrong shows on a step once the operator has been through it; the master's reasons always show
  const stepReasons = byStep[step].filter((reason) => reason.source === "server" || visited.includes(step));
  const index = pages.indexOf(step);

  const stepProps: StepProps = { draft, update, reasons: stepReasons };
  let body;
  switch (step) {
    case "steps":
      body = <StepsStep {...stepProps} />;
      break;
    case "input":
      body = <InputStep {...stepProps} catalog={catalogState} />;
      break;
    case "domain":
      body = <DomainStep {...stepProps} />;
      break;
    case "trajectories":
      body = <TrajectoriesStep {...stepProps} catalog={catalogState} />;
      break;
    case "runs":
      body = <RunsStep {...stepProps} catalog={catalogState} />;
      break;
    case "resources":
      body = <ResourcesStep {...stepProps} cluster={cluster} />;
      break;
    case "policy":
      body = <PolicyStep {...stepProps} />;
      break;
    default:
      body = (
        <ReviewStep
          yaml={yaml}
          validation={validation}
          current={validation.yaml === yaml}
          baseSeed={draft.policy.seed}
          localReasons={localReasons}
          serverReasons={serverReasons}
          onGoTo={setStep}
          onCheck={() => void check(yaml)}
          onCreate={(start) => {
            if (client) {
              setCreateMessage(null);
              creation.mutate({ start, target: client });
            }
          }}
          creating={creation.isPending}
          createMessage={createMessage}
          startBlocker={cluster.startBlocker}
        />
      );
  }

  const stepBadge = (id: WizardStepId): number => {
    const server = byStep[id].filter((reason) => reason.source === "server").length;
    const local = visited.includes(id) ? byStep[id].filter((reason) => reason.source === "local").length : 0;
    const missing = id === "resources" && visited.includes(id) ? (plan?.missing.length ?? 0) : 0;
    return id === "review" ? 0 : server + local + missing;
  };

  return (
    <div className="wiz">
      <header className="wiz-head panel">
        <div>
          <h3>New campaign</h3>
          <p className="meta">Your entries are kept in this browser until the campaign is created or you discard them.</p>
        </div>
        <div className="wiz-head-actions">
          <button type="button" onClick={onClose}>
            Close, keep the draft
          </button>
          <button
            type="button"
            className="wiz-remove"
            onClick={() => {
              if (window.confirm("Discard everything entered in the wizard?")) {
                reset();
                resetValidation();
                setCreateMessage(null);
              }
            }}
          >
            Discard the draft
          </button>
        </div>
      </header>
      <PresetBar
        draft={draft}
        catalog={stacks.data ? builderCatalog : null}
        onLoad={(next) => {
          replaceDraft(next);
          resetValidation();
          setCreateMessage(null);
        }}
      />
      <nav className="wiz-steps" aria-label="Wizard steps">
        <ol>
          {pages.map((id, at) => {
            const count = stepBadge(id);
            return (
              <li key={id}>
                <button type="button" className={`wiz-step-tab${id === step ? " wiz-step-tab--on" : ""}${count > 0 ? " wiz-step-tab--bad" : ""}`} aria-current={id === step ? "step" : undefined} onClick={() => setStep(id)}>
                  <span className="wiz-step-number">{at + 1}</span>
                  <span className="wiz-step-label">{WIZARD_STEP_LABELS[id]}</span>
                  {count > 0 && (
                    <span className="wiz-step-count" title={`${count} ${count === 1 ? "problem" : "problems"}`}>
                      {count}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
      <div className="wiz-body panel">{body}</div>
      <footer className="wiz-foot">
        <button type="button" disabled={index === 0} onClick={() => setStep(pages[index - 1])}>
          Back
        </button>
        {step !== "review" && (
          <>
            <button type="button" className="primary-btn accent" onClick={() => setStep(pages[index + 1])}>
              Next: {WIZARD_STEP_LABELS[pages[index + 1]]}
            </button>
            <button type="button" onClick={() => setStep("review")}>
              Review the config
            </button>
          </>
        )}
      </footer>
    </div>
  );
}
