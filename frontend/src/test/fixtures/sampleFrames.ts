import type { SimulationFrame } from "../../domain/simulation/types";

function buildFrame(timestamp: number): SimulationFrame {
  const ownX = 50 + timestamp * 0.8;
  const tgtX = 250 - timestamp * 0.6;
  const tgtY = 160 + Math.sin(timestamp / 8) * 20;
  const relationId = "own_ship:target_1";

  return {
    timestamp,
    timeStep: 1,
    actors: [
      {
        id: "own_ship",
        name: "own_ship",
        isVessel: true,
        isOwnShip: true,
        type: "CargoShip",
        length: 35,
        breadth: 8,
        safetyRadius: 12,
        height: 6,
        draft: 2.5,
        mass: 120000,
        rudderLength: 1.2,
        propellerDiameter: 0.9,
        maxSpeed: 15,
        maxAngularSpeed: 0.12,
        maxAcceleration: 0.8,
      },
      {
        id: "target_1",
        name: "target_1",
        isVessel: true,
        isOwnShip: false,
        type: "FishingVessel",
        length: 22,
        breadth: 6,
        safetyRadius: 10,
        maxSpeed: 12,
      },
    ],
    statesByActorId: {
      own_ship: { x: ownX, y: 120, speed: 6.5, heading: 0 },
      target_1: { x: tgtX, y: tgtY, speed: 5.8, heading: 2.9 },
    },
    trajectoriesByActorId: {},
    situationContexts: [
      {
        relationId,
        actor1Id: "own_ship",
        actor2Id: "target_1",
        situationType: "CROSSING",
        situationLabel: "Crossing from starboard",
        startTimestamp: 0,
        timeSpentInCurrentContext: timestamp,
        avoidanceDirectionByActorId: { own_ship: "RIGHT", target_1: "LEFT" },
        isGiveWayByActorId: { own_ship: true, target_1: false },
        globalAvoidanceDirectionByActorId: { own_ship: "RIGHT", target_1: "LEFT" },
        globalGiveWayByActorId: { own_ship: true, target_1: false },
      },
    ],
    colregsStates: [
      {
        relationId,
        actorsSeeEachOther: true,
        actorsPassedEachOther: false,
        actorsViolateSafetyDomain: timestamp > 140,
        actorsOnCollisionCourse: timestamp > 100,
        actorsHaveLowTcpa: timestamp > 120,
        rightOfStartStateByActorId: { own_ship: false, target_1: true },
        leftOfStartStateByActorId: { own_ship: true, target_1: false },
        haveBeenInRightManeuverByActorId: { own_ship: timestamp > 90, target_1: false },
        haveBeenInLeftManeuverByActorId: { own_ship: false, target_1: false },
        passedPotentialCollisionDomainByActorId: { own_ship: false, target_1: false },
        inFrontOfPotentialCollisionDomainByActorId: { own_ship: false, target_1: false },
      },
    ],
    ruleResults: [
      {
        relationId,
        evaluations: [
          {
            ruleName: "Rule 15",
            description: "Crossing situation give-way action.",
            result: timestamp > 150 ? "FAILED" : "PASSED",
          },
        ],
        failedRules: timestamp > 150 ? ["Rule 15"] : [],
        overallStatus: timestamp > 150 ? "FAILED" : "NOT_FAILED",
      },
    ],
    maneuverStates: [
      {
        actorId: "own_ship",
        maneuverType: timestamp > 90 ? "TURNING_RIGHT" : "KEEP_COURSE",
        previousManeuverType: "KEEP_COURSE",
        suggestedManeuvers: ["TURNING_RIGHT"],
        maneuverCount: timestamp > 90 ? 1 : 0,
        distanceMade: timestamp * 6.5,
        totalDistanceMade: timestamp * 6.5,
        timespan: timestamp,
        headingChangeDirection: timestamp > 90 ? "RIGHT" : "NONE",
        headingDiffSincePreviousDeg: timestamp > 90 ? 4.5 : 0,
        headingDiffSinceStartDeg: timestamp > 90 ? 8.4 : 0,
        headingDiffSinceReadilyApparentDeg: timestamp > 90 ? 6.2 : 0,
        startTimestamp: 0,
        currentTimestamp: timestamp,
        justStarted: timestamp === 90,
        readilyApparentTimePassed: timestamp > 95,
      },
    ],
    metrics: {
      distanceByRelationId: { [relationId]: Math.max(10, 220 - timestamp) },
      dcpaByRelationId: { [relationId]: Math.max(5, 40 - timestamp / 6) },
      tcpaByRelationId: { [relationId]: Math.max(0, 120 - timestamp) },
      dsIndexByRelationId: { [relationId]: Math.min(1, timestamp / 180) },
    },
  };
}

export const sampleFrames: SimulationFrame[] = Array.from({ length: 200 }, (_, i) =>
  buildFrame(i)
);
