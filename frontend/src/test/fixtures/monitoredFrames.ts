/**
 * Frames as `gateway.serialization.serialize_monitored_frame` puts them on the wire (and as the
 * frames artifact of `monitoring.post_hoc` stores them): the key names of the backend before
 * `domain/simulation/protocol.ts` normalizes them (`rules`, `failedRuleNames`, `isFailed`,
 * `giveWayByActorId`, `actors...ById`, `headingChange`, `metrics.relations`). Two vessels,
 * actors `0` (own ship) and `1`, relation `0->1`; the give-way vessel fails Rule 16 from `failFrom` on.
 * `monitorHistory` adds the fields of the current wire format (rule ids, first failure times,
 * CPA positions); without it a frame is in the older format the frontend falls back on.
 */

export const RULE_16 = "Rule 16: Give-Way Vessel Takes Early and Substantial Action";
export const RULE_8 = "Rule 8: Passing at a Safe Distance";

export interface MonitoredFrameOptions {
  /** Seconds of the frame. */
  timestamp: number;
  /** Seconds between frames. */
  timeStep?: number;
  /** The timestamp from which Rule 16 counts as failed; never when omitted. */
  failFrom?: number;
  /**
   * Add what the monitor sends since 2026-10-30: `ruleId` and `firstFailedAt` per rule and
   * `cpaPositionsByActorId` per relation. Left out, the frame is an older one.
   */
  monitorHistory?: boolean;
}

export const RULE_16_ID = "rule:16:give-way-vessel-takes-early-and-substantial-action:0-0:0";
export const RULE_8_ID = "rule:8:passing-at-a-safe-distance:0-1:-";
/** Where the fixture's vessels meet at their closest point of approach, while it is ahead. */
export const CPA_POSITIONS = { "0": { x: 300, y: 130 }, "1": { x: 310, y: 140 } };

function actor(id: string, name: string, own: boolean): Record<string, unknown> {
  return {
    id,
    name,
    type: own ? "CargoShip" : "FishingVessel",
    isVessel: true,
    isOwnShip: own,
    length: own ? 35 : 22,
    breadth: own ? 8 : 6,
    height: 6,
    draft: 2.5,
    mass: 120000,
    safetyRadius: own ? 12 : 10,
    maxSpeed: 15,
    maxAngularSpeed: 0.12,
    maxAcceleration: 0.8,
    rudderMass: 20,
    rudderLength: 1.2,
    rudderWidth: 0.2,
    rudderHeight: 0.8,
    propellerDiameter: 0.9,
    thrusterMass: 15,
    motorLength: 1.1,
  };
}

export function monitoredFrame({ timestamp, timeStep = 1, failFrom, monitorHistory = false }: MonitoredFrameOptions): Record<string, unknown> {
  const failed = failFrom !== undefined && timestamp >= failFrom;
  const relationId = "0->1";
  const tcpa = 60 - timestamp;
  const history = (ruleId: string, firstFailedAt: number | null) => (monitorHistory ? { ruleId, firstFailedAt } : {});
  return {
    scenarioId: "run-record-11",
    timestamp,
    timeStep,
    actors: [actor("0", "os", true), actor("1", "ts1", false)],
    statesByActorId: {
      "0": { x: 50 + timestamp * 4, y: 120, speed: 6.5, heading: 0 },
      "1": { x: 450 - timestamp * 3, y: 200 - timestamp, speed: 5.8, heading: Math.PI },
    },
    situationContexts: [
      {
        relationId,
        actor1Id: "0",
        actor2Id: "1",
        situationType: "CROSSING",
        situationLabel: "Crossing from starboard",
        startTimestamp: 0,
        avoidanceDirectionByActorId: { "0": "RIGHT", "1": "LEFT" },
        globalAvoidanceDirectionByActorId: { "0": "RIGHT", "1": "LEFT" },
        effectiveAvoidanceDirectionByActorId: { "0": "RIGHT", "1": "LEFT" },
        giveWayByActorId: { "0": true, "1": false },
        globalGiveWayByActorId: { "0": true, "1": false },
        timeSpentInCurrentContext: timestamp,
        safetyDomainsByActorId: {
          "0": { center: [50 + timestamp * 4, 120], heading: 0, shape: "circle", radius: 40 },
          "1": { center: [450 - timestamp * 3, 200 - timestamp], heading: Math.PI, shape: "ellipse", a: 60, b: 30 },
        },
        staticAvoidanceDomainsByActorId: { "0": [{ center: [200, 120], radius: 30 }], "1": [] },
        maneuveringDomainsByActorId: {
          "0": {
            vertices: [
              [100, 120],
              [160, 80],
              [220, 80],
              [280, 120],
            ],
            holdPolyline: [
              [100, 120],
              [160, 80],
              [220, 80],
              [280, 120],
            ],
            holdHeadingChangeDeg: 30,
          },
        },
      },
    ],
    colregsStates: [
      {
        relationId,
        actorsSeeEachOther: true,
        visibilityDistance: "in",
        actorsPassedEachOther: false,
        actorsViolateSafetyDomain: failed,
        actorsOnCollisionCourse: timestamp > 10,
        actorsHaveLowTcpa: timestamp > 20,
        currentTimestamp: timestamp,
        timeSpentInCurrentContext: timestamp,
        actorsRightOfStartStateById: { "0": false, "1": true },
        actorsLeftOfStartStateById: { "0": true, "1": false },
        actorsHaveBeenInRightManeuverById: { "0": timestamp > 15, "1": false },
        actorsHaveBeenInLeftManeuverById: { "0": false, "1": false },
        actorsPassedPotentialCollisionDomainById: { "0": false, "1": false },
        actorsInFrontOfPotentialCollisionDomainById: { "0": false, "1": false },
      },
    ],
    ruleResults: [
      {
        relationId,
        isFailed: failed,
        failedRuleNames: failed ? [RULE_16] : [],
        rules: [
          {
            name: RULE_16,
            title: "Give-Way Vessel Takes Early and Substantial Action",
            ruleNumber: "16",
            kind: "rule",
            description: "A vessel directed to keep out of the way should take early and substantial action to keep well clear.",
            subjectActorId: "0",
            subjectActorName: "os",
            result: failed ? "FAILED" : "PASSED",
            ...history(RULE_16_ID, failed ? failFrom! : null),
          },
          {
            name: RULE_8,
            title: "Passing at a Safe Distance",
            ruleNumber: "8",
            kind: "rule",
            description: "Action taken to avoid collision should result in the vessels passing at a safe distance.",
            subjectActorId: null,
            subjectActorName: "",
            result: timestamp > 20 ? "UNKNOWN" : "PASSED",
            ...history(RULE_8_ID, null),
          },
        ],
      },
    ],
    maneuverStates: [
      {
        relationId: "0->1",
        maneuverType: timestamp > 15 ? "TURNING_RIGHT" : "KEEP_COURSE",
        previousManeuverType: "KEEP_COURSE",
        maneuverCount: timestamp > 15 ? 1 : 0,
        startTimestamp: 0,
        currentTimestamp: timestamp,
        timespan: timestamp,
        distanceMade: timestamp * 6.5,
        totalDistanceMade: timestamp * 6.5,
        justStarted: timestamp === 16,
        readilyApparentTimePassed: timestamp > 18,
        headingChange: {
          detectedDirection: timestamp > 15 ? "RIGHT" : "NONE",
          headingDiffSincePreviousDeg: timestamp > 15 ? 4.5 : 0,
          headingDiffSinceStartDeg: timestamp > 15 ? 8.4 : 0,
          headingDiffSinceReadilyApparentTimeDeg: 0,
        },
        speedChange: { speedDiffSincePrevious: 0, speedDiffSinceStart: 0, speedDiffSinceReadilyApparentTime: 0 },
        suggestedManeuvers: ["TURNING_RIGHT"],
        suggestionInfo: {},
      },
    ],
    metrics: {
      scene: { dcpa: 12.5, tcpa: 40, dangerSector: 0.4, proximityIndex: 0.2 },
      relations: {
        [relationId]: {
          distance: Math.max(10, 400 - timestamp * 7),
          tcpa: monitorHistory ? tcpa : Math.max(0, tcpa),
          dcpa: 12.5,
          safetyDistance: 50,
          visibilityDistance: 5000,
          ...(monitorHistory ? { cpaPositionsByActorId: tcpa >= 0 ? CPA_POSITIONS : null } : {}),
        },
      },
    },
  };
}

/** `count` frames one second apart; a failure from `failFrom` on. */
export function monitoredFrames(count: number, failFrom?: number, monitorHistory = false): Record<string, unknown>[] {
  return Array.from({ length: count }, (_, index) => monitoredFrame({ timestamp: index, failFrom, monitorHistory }));
}
