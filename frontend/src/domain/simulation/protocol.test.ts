import { describe, expect, it } from "vitest";
import { parseFrame, parseServerMessage } from "./protocol";
import { CPA_POSITIONS, RULE_16_ID, RULE_8_ID, monitoredFrame } from "../../test/fixtures/monitoredFrames";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { sampleRunRecordingMessages } from "../../test/fixtures/historyViews";

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

  it("parses mqtt_broker_status with the control node broker", () => {
    const msg = parseServerMessage({
      type: "mqtt_broker_status",
      status: "connected",
      controlNodeBroker: "cluster-broker:1883",
    });
    expect(msg.kind).toBe("mqtt_broker_status");
    if (msg.kind === "mqtt_broker_status") {
      expect(msg.status).toBe("connected");
      expect(msg.controlNodeBroker).toBe("cluster-broker:1883");
    }
  });

  it("parses mqtt_broker_status from a server without a control node broker", () => {
    const msg = parseServerMessage({ type: "mqtt_broker_status", status: "disconnected" });
    expect(msg.kind === "mqtt_broker_status" && msg.controlNodeBroker).toBe(null);
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

  it("parses every status of run_recording", () => {
    const parsed = sampleRunRecordingMessages.map((raw) => parseServerMessage(raw));
    expect(parsed.map((msg) => msg.kind === "run_recording" && msg.status)).toEqual(["recording", "saved", "failed", "unavailable"]);
    expect(parsed[0]).toEqual({
      kind: "run_recording",
      status: "recording",
      campaignId: "wb3",
      caseId: 1,
      message: "Recording the run as a workbench entry",
    });
    expect(parsed[3]).toEqual({
      kind: "run_recording",
      status: "unavailable",
      campaignId: null,
      caseId: null,
      message: "the gateway runs without a control node",
    });
  });

  it("parses run_recording without the optional fields and with snake_case names", () => {
    expect(parseServerMessage({ type: "run_recording", status: "unavailable" })).toEqual({
      kind: "run_recording",
      status: "unavailable",
      campaignId: null,
      caseId: null,
      message: null,
    });
    const msg = parseServerMessage({ type: "run_recording", status: "saved", campaign_id: "wb9", case_id: 4 });
    expect(msg.kind === "run_recording" && [msg.campaignId, msg.caseId]).toEqual(["wb9", 4]);
  });

  it("rejects a run_recording status it does not know", () => {
    expect(() => parseServerMessage({ type: "run_recording", status: "paused" })).toThrow();
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

  it("parses the ground control station ports of a simulation_status", () => {
    const msg = parseServerMessage({
      type: "simulation_status",
      status: "ready to start",
      groundControlPortsByAgentId: { "1": 49153 },
    });
    expect(msg.kind).toBe("simulation_status");
    if (msg.kind === "simulation_status") {
      expect(msg.groundControlPortsByAgentId).toEqual({ "1": 49153 });
    }
  });

  it("gives a simulation_status without ports an empty port map", () => {
    const msg = parseServerMessage({ type: "simulation_status", status: "running" });
    if (msg.kind === "simulation_status") {
      expect(msg.groundControlPortsByAgentId).toEqual({});
    }
  });

  it("parses stack_options", () => {
    const combination = {
      simulatorType: "Kinematic",
      asvSoftware: "replay",
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
      asvSoftware: ["replay", "usv_navigation", "mission_planner"],
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
