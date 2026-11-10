import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type {
  ActorStaticInfo,
  ColregsMonitorStateData,
  ManeuverStateData,
  SituationContextData,
} from "../../../domain/simulation/types";
import { ColregsMonitorStateSection } from "./ColregsMonitorStateSection";
import { ManeuversSection } from "./ManeuversSection";
import {
  COLREGS_STATE_COLUMN_HINTS,
  COLREGS_STATE_HINTS,
  MANEUVER_HINTS,
  METRIC_HINTS,
  SITUATION_CONTEXT_HINTS,
} from "./monitorHints";
import { MonitorMetricsSection } from "./MonitorMetricsSection";
import { SituationContextsSection } from "./SituationContextsSection";

// Every column, tile and flag of the monitor sections says what it means in a tooltip.

function actor(id: string, name: string): ActorStaticInfo {
  return { id, name, isVessel: true, isOwnShip: id === "0", type: "vessel", length: 30, breadth: 8, safetyRadius: 50 };
}

const ACTORS = [actor("0", "os"), actor("1", "ts1")];

const CONTEXT: SituationContextData = {
  relationId: "0->1",
  actor1Id: "0",
  actor2Id: "1",
  situationType: "HEAD_ON",
  situationLabel: "Head-On",
  startTimestamp: 0,
  timeSpentInCurrentContext: 12,
  avoidanceDirectionByActorId: { "0": "RIGHT", "1": "RIGHT" },
  isGiveWayByActorId: { "0": true, "1": true },
  globalAvoidanceDirectionByActorId: { "0": "RIGHT", "1": "RIGHT" },
  effectiveAvoidanceDirectionByActorId: { "0": "RIGHT", "1": "RIGHT" },
  globalGiveWayByActorId: { "0": true, "1": true },
};

const STATE: ColregsMonitorStateData = {
  relationId: "0->1",
  actorsSeeEachOther: true,
  actorsPassedEachOther: false,
  actorsViolateSafetyDomain: false,
  actorsOnCollisionCourse: true,
  actorsHaveLowTcpa: false,
  rightOfStartStateByActorId: { "0": false, "1": false },
  leftOfStartStateByActorId: { "0": false, "1": false },
  haveBeenInRightManeuverByActorId: { "0": false, "1": false },
  haveBeenInLeftManeuverByActorId: { "0": false, "1": false },
  passedPotentialCollisionDomainByActorId: { "0": false, "1": false },
  inFrontOfPotentialCollisionDomainByActorId: { "0": false, "1": false },
};

const MANEUVER: ManeuverStateData = {
  actorId: "0",
  relationId: "0->0",
  maneuverType: "COURSE_CHANGE_TO_THE_RIGHT",
  previousManeuverType: "PERSISTING_COURSE",
  suggestedManeuvers: ["PERSISTING_COURSE"],
  maneuverCount: 2,
  distanceMade: 40,
  totalDistanceMade: 400,
  timespan: 15,
  headingChangeDirection: "RIGHT",
  headingDiffSincePreviousDeg: -4,
  headingDiffSinceStartDeg: -12,
  headingDiffSinceReadilyApparentDeg: -12,
  speedDiffSincePrevious: 0,
  speedDiffSinceStart: 0,
  speedDiffSinceReadilyApparent: 0,
  startTimestamp: 30,
  currentTimestamp: 45,
  justStarted: false,
  readilyApparentTimePassed: false,
};

/** The tooltip of the element showing `label`. */
function hintOf(label: string): string | null {
  return screen.getByText(label).getAttribute("title");
}

describe("monitor section tooltips", () => {
  it("explains the columns of a situation context", () => {
    render(<SituationContextsSection persistKey="test:contexts" contexts={[CONTEXT]} actors={ACTORS} />);

    expect(hintOf("Avoidance")).toBe(SITUATION_CONTEXT_HINTS.avoidance);
    expect(hintOf("Judged")).toBe(SITUATION_CONTEXT_HINTS.judged);
    expect(hintOf("Role")).toBe(SITUATION_CONTEXT_HINTS.role);
    expect(hintOf("Global avoid.")).toBe(SITUATION_CONTEXT_HINTS.globalAvoidance);
    expect(hintOf("Global role")).toBe(SITUATION_CONTEXT_HINTS.globalRole);
    expect(hintOf("12 s in context")).toBe(SITUATION_CONTEXT_HINTS.timeInContext);
  });

  it("explains the flags and the per-vessel columns of the COLREGS monitor state", () => {
    render(<ColregsMonitorStateSection persistKey="test:states" states={[STATE]} actors={ACTORS} />);

    expect(hintOf("In sight")).toBe(`In sight: yes. ${COLREGS_STATE_HINTS.inSight}`);
    expect(hintOf("Passed each other")).toBe(`Passed each other: no. ${COLREGS_STATE_HINTS.passedEachOther}`);
    expect(hintOf("Collision course")).toBe(`Collision course: yes. ${COLREGS_STATE_HINTS.collisionCourse}`);
    expect(hintOf("Safety domain violated")).toBe(`Safety domain violated: no. ${COLREGS_STATE_HINTS.safetyDomainViolated}`);
    expect(hintOf("Low TCPA")).toBe(`Low TCPA: no. ${COLREGS_STATE_HINTS.lowTcpa}`);

    expect(hintOf("Right of start")).toBe(COLREGS_STATE_COLUMN_HINTS.rightOfStartStateByActorId);
    expect(hintOf("Left of start")).toBe(COLREGS_STATE_COLUMN_HINTS.leftOfStartStateByActorId);
    expect(hintOf("Was in right man.")).toBe(COLREGS_STATE_COLUMN_HINTS.haveBeenInRightManeuverByActorId);
    expect(hintOf("Was in left man.")).toBe(COLREGS_STATE_COLUMN_HINTS.haveBeenInLeftManeuverByActorId);
    expect(hintOf("Passed coll. domain")).toBe(COLREGS_STATE_COLUMN_HINTS.passedPotentialCollisionDomainByActorId);
    expect(hintOf("In front of domain")).toBe(COLREGS_STATE_COLUMN_HINTS.inFrontOfPotentialCollisionDomainByActorId);
  });

  it("explains the tiles and flags of a maneuver", () => {
    render(<ManeuversSection persistKey="test:maneuvers" maneuvers={[MANEUVER]} actors={ACTORS} />);

    expect(hintOf("Turn")).toBe(MANEUVER_HINTS.turn);
    expect(hintOf("Δ heading (prev)")).toBe(MANEUVER_HINTS.headingPrev);
    expect(hintOf("Δ heading (start)")).toBe(MANEUVER_HINTS.headingStart);
    expect(hintOf("Δ heading (RA)")).toBe(MANEUVER_HINTS.headingReadilyApparent);
    expect(hintOf("Δ speed (prev)")).toBe(MANEUVER_HINTS.speedPrev);
    expect(hintOf("Δ speed (start)")).toBe(MANEUVER_HINTS.speedStart);
    expect(hintOf("Δ speed (RA)")).toBe(MANEUVER_HINTS.speedReadilyApparent);
    expect(hintOf("Distance made")).toBe(MANEUVER_HINTS.distanceMade);
    expect(hintOf("Just started")).toBe(`Just started: no. ${MANEUVER_HINTS.justStarted}`);
    expect(hintOf("Readily apparent time passed")).toBe(
      `Readily apparent time passed: no. ${MANEUVER_HINTS.readilyApparentTimePassed}`,
    );
    expect(hintOf("timespan")).toBe(MANEUVER_HINTS.timespan);
    expect(hintOf("Suggested")).toBe(MANEUVER_HINTS.suggested);
    expect(hintOf("x2")).toBe(MANEUVER_HINTS.maneuverCount);
  });

  it("explains the distance and closest point of approach tiles of the metrics", () => {
    render(
      <MonitorMetricsSection
        persistKey="test:metrics"
        metrics={{ relations: { "0->1": { distance: 900, dcpa: 20, tcpa: 60 } } }}
      />,
    );

    expect(hintOf("Distance")).toBe(METRIC_HINTS.distance);
    expect(hintOf("DCPA")).toBe(METRIC_HINTS.dcpa);
    expect(hintOf("TCPA")).toBe(METRIC_HINTS.tcpa);
  });
});
