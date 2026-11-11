import { describe, expect, it } from "vitest";
import { parseFrame, parseServerMessage } from "./protocol";
import { CPA_POSITIONS, RULE_16_ID, RULE_8_ID, monitoredFrame } from "../../test/fixtures/monitoredFrames";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { RETIRED_GATEWAY_MESSAGES } from "./wireTypes";

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
  it("does not read a frame without a type: the gateway pushes none", () => {
    const raw = sampleFrames[0];
    expect(parseServerMessage(raw)).toEqual({ kind: "unknown", raw });
  });

  it.each([...RETIRED_GATEWAY_MESSAGES])("does not read %s, a message of the former live session", (type) => {
    const raw = { type, status: "connected", frames: [sampleFrames[0]], chunkIndex: 0, isLast: true };
    expect(parseServerMessage(raw)).toEqual({ kind: "unknown", raw });
  });

  it("names the messages a control node from before the worker-only revision still sends", () => {
    expect([...RETIRED_GATEWAY_MESSAGES].sort()).toEqual(["frame", "monitor_status", "mqtt_broker_status", "run_recording", "simulation_status", "simulation_trajectory_chunk"]);
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

  it("parses stack_options", () => {
    const combination = {
      simulatorType: "Kinematic",
      asvSystem: "replay",
      controlLayer: "ardupilot",
      available: false,
      status: "unavailable",
      reason: "the kinematic sim integrates control internally",
      interactiveOnly: false,
      repeatabilityTier: null,
      maxSpeedup: null,
      speedupUnlimited: false,
      wind: null,
      waves: null,
    };
    const msg = parseServerMessage({
      type: "stack_options",
      simulatorTypes: ["Kinematic", "Gazebo", "ArduPilot Sim"],
      asvSystem: ["replay", "usv_navigation", "mission_planner"],
      controlLayers: ["ardupilot", "custom", "none"],
      combinations: [combination],
    });
    expect(msg.kind).toBe("stack_options");
    if (msg.kind === "stack_options") {
      expect(msg.options.simulatorTypes).toEqual(["Kinematic", "Gazebo", "ArduPilot Sim"]);
      expect(msg.options.combinations).toEqual([combination]);
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

describe("trajectory_generation_result", () => {
  const result = {
    type: "trajectory_generation_result",
    requestId: "r1",
    trajectoryData: { trajectories: { scene_list: [], time_step: 15 } },
    valid: true,
    errorMessage: null,
  };

  it("reads complete when the backend sends it", () => {
    const partial = parseServerMessage({ ...result, complete: false });
    const complete = parseServerMessage({ ...result, complete: true });
    expect(partial.kind === "trajectory_generation_result" && partial.complete).toBe(false);
    expect(complete.kind === "trajectory_generation_result" && complete.complete).toBe(true);
  });

  it("leaves complete unknown when the backend does not send it", () => {
    const msg = parseServerMessage(result);
    expect(msg.kind).toBe("trajectory_generation_result");
    if (msg.kind === "trajectory_generation_result") {
      expect(msg.complete).toBeNull();
      expect(msg.valid).toBe(true);
    }
  });
});

describe("parseFrame: rule ids, first failures and CPA positions", () => {
  it("keeps the rule id and first failure time of every rule", () => {
    const frame = parseFrame(monitoredFrame({ timestamp: 30, failFrom: 12, monitorHistory: true }));
    const rules = frame.ruleResults[0]!.evaluations;
    expect(rules.map((rule) => [rule.ruleId, rule.firstFailedAt])).toEqual([
      [RULE_16_ID, 12],
      [RULE_8_ID, null],
    ]);
  });

  it("collects the CPA positions per relation and leaves out a relation without one", () => {
    expect(parseFrame(monitoredFrame({ timestamp: 30, monitorHistory: true })).metrics?.cpaPositionsByRelationId).toEqual({
      "0->1": CPA_POSITIONS,
    });
    const passed = parseFrame(monitoredFrame({ timestamp: 70, monitorHistory: true }));
    expect(passed.metrics?.cpaPositionsByRelationId).toBeUndefined();
    expect(passed.metrics?.relations?.["0->1"]?.cpaPositionsByActorId).toBeNull();
  });

  it("drops malformed CPA positions", () => {
    const raw = monitoredFrame({ timestamp: 30, monitorHistory: true });
    const relation = ((raw.metrics as Record<string, unknown>).relations as Record<string, Record<string, unknown>>)["0->1"]!;
    relation.cpaPositionsByActorId = { "0": { x: 1, y: "2" }, "1": { x: 3, y: 4 } };
    expect(parseFrame(raw).metrics?.cpaPositionsByRelationId).toBeUndefined();
  });

  it("leaves the fields out on an older frame", () => {
    const frame = parseFrame(monitoredFrame({ timestamp: 30, failFrom: 12 }));
    for (const rule of frame.ruleResults[0]!.evaluations) {
      expect(rule).not.toHaveProperty("ruleId");
      expect(rule).not.toHaveProperty("firstFailedAt");
    }
    expect(frame.metrics?.cpaPositionsByRelationId).toBeUndefined();
  });
});
