import { describe, expect, it } from "vitest";
import { parseFrame, parseServerMessage } from "./protocol";
import { sampleFrames } from "../../test/fixtures/sampleFrames";

describe("parseFrame", () => {
  it("accepts canonical simulation payload", () => {
    const parsed = parseFrame(sampleFrames[0]);
    expect(parsed.timestamp).toBe(0);
    expect(parsed.actors.length).toBeGreaterThan(0);
    expect(parsed.actors[0]?.safetyRadius).toBeGreaterThan(0);
  });

  it("maps legacy wire field radius to safetyRadius", () => {
    const base = sampleFrames[0];
    const legacy = {
      ...base,
      actors: base.actors.map((a) => {
        const { safetyRadius: _s, ...rest } = a;
        void _s;
        return { ...rest, radius: a.safetyRadius };
      }),
    };
    const parsed = parseFrame(legacy);
    expect(parsed.actors[0]?.safetyRadius).toBe(base.actors[0]?.safetyRadius);
  });

  it("maps legacy thrustersMass to thrusterMass", () => {
    const base = sampleFrames[0];
    const first = base.actors[0];
    expect(first).toBeDefined();
    const withLegacy = {
      ...base,
      actors: base.actors.map((a, i) =>
        i === 0 ? { ...a, thrustersMass: 42 } : a
      ),
    };
    const parsed = parseFrame(withLegacy);
    expect(parsed.actors[0]?.thrusterMass).toBe(42);
  });

  it("throws for invalid payload", () => {
    expect(() => parseFrame({ hello: "world" })).toThrow();
  });
});

describe("parseServerMessage", () => {
  it("parses legacy raw frame without type", () => {
    const msg = parseServerMessage(sampleFrames[0]);
    expect(msg.kind).toBe("frame");
    if (msg.kind === "frame") {
      expect(msg.frame.timestamp).toBe(0);
    }
  });

  it("parses initial_state envelope with trajectory length", () => {
    const msg = parseServerMessage({
      type: "initial_state",
      timeStep: 1,
      totalTrajectoryLength: 240,
      frame: sampleFrames[0],
    });
    expect(msg.kind).toBe("initial_state");
    if (msg.kind === "initial_state") {
      expect(msg.scenarioId).toBeNull();
      expect(msg.totalTrajectoryLength).toBe(240);
    }
  });

  it("parses initial_state scenarioId", () => {
    const msg = parseServerMessage({
      type: "initial_state",
      scenarioId: "scen-99",
      timeStep: 1,
      totalTrajectoryLength: 100,
    });
    expect(msg.kind).toBe("initial_state");
    if (msg.kind === "initial_state") {
      expect(msg.scenarioId).toBe("scen-99");
    }
  });

  it("parses simulation_trajectory_chunk", () => {
    const msg = parseServerMessage({
      type: "simulation_trajectory_chunk",
      scenarioId: "scen-a",
      fromTimestamp: 0,
      toTimestamp: 2,
      frames: sampleFrames.slice(0, 3),
    });
    expect(msg.kind).toBe("simulation_trajectory_chunk");
    if (msg.kind === "simulation_trajectory_chunk") {
      expect(msg.scenarioId).toBe("scen-a");
      expect(msg.frames.length).toBe(3);
    }
  });

  it("parses preview_trajectory_chunk", () => {
    const msg = parseServerMessage({
      type: "preview_trajectory_chunk",
      scenarioId: "scen-b",
      fromTimestamp: 0,
      toTimestamp: 2,
      frames: sampleFrames.slice(0, 3),
    });
    expect(msg.kind).toBe("preview_trajectory_chunk");
    if (msg.kind === "preview_trajectory_chunk") {
      expect(msg.scenarioId).toBe("scen-b");
      expect(msg.frames.length).toBe(3);
    }
  });

  it("accepts trajectory frames with backend alias keys", () => {
    const base = sampleFrames[0];
    const msg = parseServerMessage({
      type: "preview_trajectory_chunk",
      scenarioId: "scen-c",
      fromTimestamp: 0,
      toTimestamp: 0,
      frames: [
        {
          ...base,
          situationContexts: base.situationContexts.map((ctx) => ({
            ...ctx,
            giveWayByActorId: ctx.isGiveWayByActorId,
            isGiveWayByActorId: undefined,
            timeSpentInCurrentContext: undefined,
          })),
          colregsStates: base.colregsStates.map((state) => ({
            ...state,
            actorsRightOfStartStateById: state.rightOfStartStateByActorId,
            actorsLeftOfStartStateById: state.leftOfStartStateByActorId,
            actorsHaveBeenInRightManeuverById: state.haveBeenInRightManeuverByActorId,
            actorsHaveBeenInLeftManeuverById: state.haveBeenInLeftManeuverByActorId,
            actorsPassedPotentialCollisionDomainById: state.passedPotentialCollisionDomainByActorId,
            actorsInFrontOfPotentialCollisionDomainById: state.inFrontOfPotentialCollisionDomainByActorId,
            rightOfStartStateByActorId: undefined,
            leftOfStartStateByActorId: undefined,
            haveBeenInRightManeuverByActorId: undefined,
            haveBeenInLeftManeuverByActorId: undefined,
            passedPotentialCollisionDomainByActorId: undefined,
            inFrontOfPotentialCollisionDomainByActorId: undefined,
          })),
          ruleResults: base.ruleResults.map((result) => ({
            relationId: result.relationId,
            isFailed: result.overallStatus === "FAILED",
            failedRuleNames: result.failedRules,
            rules: result.evaluations.map((evaluation) => ({
              name: evaluation.ruleName,
              description: evaluation.description,
              result: evaluation.result,
            })),
          })),
          maneuverStates: base.maneuverStates.map((state) => ({
            relationId: `${state.actorId}->${state.actorId}`,
            maneuverType: state.maneuverType,
            maneuverCount: state.maneuverCount,
            distanceMade: state.distanceMade,
            totalDistanceMade: state.totalDistanceMade,
            timespan: state.timespan,
            startTimestamp: state.startTimestamp,
            currentTimestamp: state.currentTimestamp,
            justStarted: state.justStarted,
            readilyApparentTimePassed: state.readilyApparentTimePassed,
            headingChange: {
              detectedDirection: state.headingChangeDirection,
              headingDiffSincePreviousDeg: state.headingDiffSincePreviousDeg,
              headingDiffSinceStartDeg: state.headingDiffSinceStartDeg,
              headingDiffSinceReadilyApparentTimeDeg: state.headingDiffSinceReadilyApparentDeg,
            },
          })),
          metrics: {
            scene: {},
            relations: {
              [base.ruleResults[0].relationId]: {
                distance: 1234.5,
                dcpa: 56.7,
                tcpa: 89.1,
                dangerSector: 0.42,
              },
            },
          },
        },
      ],
    });
    expect(msg.kind).toBe("preview_trajectory_chunk");
    if (msg.kind === "preview_trajectory_chunk") {
      expect(msg.frames[0].situationContexts[0].isGiveWayByActorId).toBeDefined();
      expect(msg.frames[0].colregsStates[0].rightOfStartStateByActorId).toBeDefined();
      expect(msg.frames[0].ruleResults[0].overallStatus).toMatch(/FAILED|NOT_FAILED/);
      expect(msg.frames[0].ruleResults[0].evaluations[0]?.ruleName).toBeTruthy();
      expect(msg.frames[0].maneuverStates[0].actorId).toBeTruthy();
      const relationId = base.ruleResults[0].relationId;
      expect(msg.frames[0].metrics?.distanceByRelationId?.[relationId]).toBe(1234.5);
      expect(msg.frames[0].metrics?.dcpaByRelationId?.[relationId]).toBe(56.7);
      expect(msg.frames[0].metrics?.tcpaByRelationId?.[relationId]).toBe(89.1);
      expect(msg.frames[0].metrics?.dsIndexByRelationId?.[relationId]).toBe(0.42);
    }
  });

  it("parses initial_state from a payload envelope", () => {
    const msg = parseServerMessage({
      type: "initial_state",
      payload: {
        scenarioId: "scenario-1",
        timeStep: 1,
        trajectoryLength: 240,
      },
    });
    expect(msg.kind).toBe("initial_state");
    if (msg.kind === "initial_state") {
      expect(msg.scenarioId).toBe("scenario-1");
      expect(msg.totalTrajectoryLength).toBe(240);
    }
  });

  it("parses waraps_status", () => {
    const msg = parseServerMessage({
      type: "waraps_status",
      status: "connected",
    });
    expect(msg.kind).toBe("waraps_status");
    if (msg.kind === "waraps_status") {
      expect(msg.status).toBe("connected");
    }
  });

  it("parses monitor_status", () => {
    const msg = parseServerMessage({
      type: "monitor_status",
      status: "disconnected",
    });
    expect(msg.kind).toBe("monitor_status");
    if (msg.kind === "monitor_status") {
      expect(msg.status).toBe("disconnected");
    }
  });

  it("parses simulation_status", () => {
    const msg = parseServerMessage({
      type: "simulation_status",
      status: "agents are preparing",
    });
    expect(msg.kind).toBe("simulation_status");
    if (msg.kind === "simulation_status") {
      expect(msg.status).toBe("agents are preparing");
    }
  });

  it("parses simulation_models with per-vessel models", () => {
    const msg = parseServerMessage({
      type: "simulation_models",
      connectionsByAgentId: {
        os: { context: "simulation", gazeboVesselModel: "<sdf><os/></sdf>" },
        ts1: { context: "simulation" },
      },
    });
    expect(msg.kind).toBe("simulation_models");
    if (msg.kind === "simulation_models") {
      expect(msg.vesselModelsByAgentId.os).toBe("<sdf><os/></sdf>");
      expect(msg.vesselModelsByAgentId.ts1).toBeNull();
    }
  });

  it("parses simulation_status starting", () => {
    const msg = parseServerMessage({
      type: "simulation_status",
      status: "starting",
    });
    expect(msg.kind).toBe("simulation_status");
    if (msg.kind === "simulation_status") {
      expect(msg.status).toBe("starting");
    }
  });

  it("parses simulation_status when offline", () => {
    const msg = parseServerMessage({
      type: "simulation_status",
      status: "offline",
    });
    expect(msg.kind).toBe("simulation_status");
    if (msg.kind === "simulation_status") {
      expect(msg.status).toBe("offline");
    }
  });

  it("parses generated_scene message", () => {
    const msg = parseServerMessage({
      type: "generated_scene",
      requestId: "req-1",
      valid: true,
      scene: sampleFrames[0],
    });
    expect(msg.kind).toBe("generated_scene");
    if (msg.kind === "generated_scene") {
      expect(msg.requestId).toBe("req-1");
      expect(msg.valid).toBe(true);
      expect(msg.scene.timestamp).toBe(0);
      expect(msg.evaluationData).toBeNull();
    }
  });

  it("defaults generated_scene valid to false when omitted", () => {
    const msg = parseServerMessage({
      type: "generated_scene",
      requestId: "req-progress",
      scene: sampleFrames[0],
    });
    expect(msg.kind).toBe("generated_scene");
    if (msg.kind === "generated_scene") {
      expect(msg.valid).toBe(false);
    }
  });

  it("parses generated_scene evaluationData dictionary", () => {
    const msg = parseServerMessage({
      type: "generated_scene",
      requestId: "req-2",
      scene: sampleFrames[0],
      evaluationData: {
        algorithm_desc: "Two_Step_CD_Rejection_Sampling",
        scenario_name: "3vessel_0obstacle",
        random_seed: 1234,
      },
    });
    expect(msg.kind).toBe("generated_scene");
    if (msg.kind === "generated_scene") {
      expect(msg.requestId).toBe("req-2");
      expect(msg.evaluationData).toEqual({
        algorithm_desc: "Two_Step_CD_Rejection_Sampling",
        scenario_name: "3vessel_0obstacle",
        random_seed: 1234,
      });
    }
  });
});
