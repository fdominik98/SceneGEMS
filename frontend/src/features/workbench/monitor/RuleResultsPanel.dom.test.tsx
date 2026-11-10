import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { RuleEvaluation, RuleResult, RuleResultData } from "../../../domain/simulation/types";
import { ActorNamesContext } from "./actorNames";
import { RULE_SCOPE_HINTS } from "./monitorHints";
import { RuleResultsPanel } from "./RuleResultsPanel";

// The COLREGS rules panel on a three-vessel frame, as the monitor sends it: every encounter
// repeats the vessel rules of its two vessels.

const NAMES = { "0": "os", "1": "ts1", "2": "ts2" };

function vesselRule(actorId: keyof typeof NAMES, result: RuleResult = "UNKNOWN"): RuleEvaluation {
  return {
    ruleId: `rule:8:readily-apparent-course-change:${actorId}-${actorId}:${actorId}`,
    ruleName: "Rule 8: Readily Apparent Course Change",
    title: "Readily Apparent Course Change",
    ruleNumber: "8",
    kind: "rule",
    description: "A course change should be readily apparent.",
    subjectActorId: actorId,
    subjectActorName: NAMES[actorId],
    result,
  };
}

function safeDistance(relation: string, result: RuleResult = "UNKNOWN"): RuleEvaluation {
  return {
    ruleId: `rule:8:passing-at-a-safe-distance:${relation}:-`,
    ruleName: "Rule 8: Passing at a Safe Distance",
    title: "Passing at a Safe Distance",
    ruleNumber: "8",
    kind: "rule",
    description: "The vessels should pass at a safe distance.",
    subjectActorId: null,
    subjectActorName: "",
    result,
  };
}

function group(relationId: string, evaluations: RuleEvaluation[]): RuleResultData {
  const failed = evaluations.filter((evaluation) => evaluation.result === "FAILED");
  return {
    relationId,
    evaluations,
    failedRules: failed.map((evaluation) => evaluation.ruleName),
    overallStatus: failed.length > 0 ? "FAILED" : "NOT_FAILED",
  };
}

function ruleResults(ownShipResult: RuleResult = "UNKNOWN"): RuleResultData[] {
  return [
    group("0->1", [safeDistance("0-1"), vesselRule("0", ownShipResult), vesselRule("1")]),
    group("0->2", [safeDistance("0-2"), vesselRule("0", ownShipResult), vesselRule("2")]),
    group("1->2", [safeDistance("1-2"), vesselRule("1"), vesselRule("2")]),
  ];
}

function renderPanel(results: RuleResultData[]) {
  return render(
    <ActorNamesContext.Provider value={NAMES}>
      <RuleResultsPanel persistKey="test:rules" ruleResults={results} situationContexts={[]} />
    </ActorNamesContext.Provider>,
  );
}

/** The group card whose head line shows `heading`. */
function groupOf(heading: string): HTMLElement {
  const head = screen
    .getAllByText(heading)
    .find((element) => element.classList.contains("rule-group-relation"));
  if (!head) {
    throw new Error(`no rule group headed ${heading}`);
  }
  return head.closest(".rule-group") as HTMLElement;
}

describe("RuleResultsPanel", () => {
  it("lists a vessel's rule once under the vessel, not under each of its encounters", async () => {
    renderPanel(ruleResults());
    await userEvent.click(screen.getByLabelText(/Show passed/));

    expect(screen.getAllByText("Readily Apparent Course Change")).toHaveLength(3);
    for (const vessel of ["os", "ts1", "ts2"]) {
      expect(within(groupOf(vessel)).getByText("Readily Apparent Course Change")).toBeInTheDocument();
      expect(within(groupOf(vessel)).getByText("1 rule")).toBeInTheDocument();
    }
    for (const pair of ["os - ts1", "os - ts2", "ts1 - ts2"]) {
      expect(within(groupOf(pair)).queryByText("Readily Apparent Course Change")).toBeNull();
      expect(within(groupOf(pair)).getByText("Passing at a Safe Distance")).toBeInTheDocument();
      expect(within(groupOf(pair)).getByText("1 rule")).toBeInTheDocument();
    }
    expect(screen.getByText("6 ok")).toBeInTheDocument();
  });

  it("counts a failed vessel rule once and leaves the vessel's encounters compliant", () => {
    renderPanel(ruleResults("FAILED"));

    expect(screen.getByText("1 failed")).toBeInTheDocument();
    expect(within(groupOf("os")).getByText("Failed")).toBeInTheDocument();
    expect(within(groupOf("os")).getByText("Readily Apparent Course Change")).toBeInTheDocument();
    for (const pair of ["os - ts1", "os - ts2", "ts1 - ts2"]) {
      expect(within(groupOf(pair)).getByText("Compliant")).toBeInTheDocument();
    }
  });

  it("explains the two scopes in tooltips", () => {
    renderPanel(ruleResults());

    expect(screen.getByText("Per vessel")).toHaveAttribute("title", RULE_SCOPE_HINTS.vessels);
    expect(screen.getByText("Per encounter")).toHaveAttribute("title", RULE_SCOPE_HINTS.encounters);
  });

  it("shows no scope headings on a frame without vessel rules", () => {
    renderPanel([group("0->1", [safeDistance("0-1")])]);

    expect(screen.queryByText("Per vessel")).toBeNull();
    expect(screen.queryByText("Per encounter")).toBeNull();
    expect(groupOf("os - ts1")).toBeInTheDocument();
  });
});
