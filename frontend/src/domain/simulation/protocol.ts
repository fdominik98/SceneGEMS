import { z } from "zod";
import type { EvaluationData, SimulationFrame } from "./types";

const stateSchema = z
  .object({
    x: z.number(),
    y: z.number(),
    speed: z.number(),
    heading: z.number(),
  })
  .passthrough();

const actorSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    isVessel: z.boolean(),
    isOwnShip: z.boolean(),
    type: z.string(),
    length: z.number(),
    breadth: z.number(),
    safetyRadius: z.number(),
    height: z.number().optional(),
    draft: z.number().optional(),
    mass: z.number().optional(),
    maxSpeed: z.number().optional(),
    maxAngularSpeed: z.number().optional(),
    maxAcceleration: z.number().optional(),
    rudderMass: z.number().optional(),
    rudderLength: z.number().optional(),
    rudderWidth: z.number().optional(),
    rudderHeight: z.number().optional(),
    propellerDiameter: z.number().optional(),
    thrusterMass: z.number().optional(),
    motorLength: z.number().optional(),
  })
  .passthrough();

const situationContextSchema = z
  .object({
    relationId: z.string(),
    actor1Id: z.string(),
    actor2Id: z.string(),
    situationType: z.string(),
    situationLabel: z.string(),
    startTimestamp: z.number(),
    timeSpentInCurrentContext: z.number(),
    avoidanceDirectionByActorId: z.record(z.string(), z.string()),
    isGiveWayByActorId: z.record(z.string(), z.boolean()),
    globalAvoidanceDirectionByActorId: z.record(z.string(), z.string()),
    globalGiveWayByActorId: z.record(z.string(), z.boolean()),
  })
  .passthrough();

const colregsStateSchema = z
  .object({
    relationId: z.string(),
    actorsSeeEachOther: z.boolean(),
    actorsPassedEachOther: z.boolean(),
    actorsViolateSafetyDomain: z.boolean(),
    actorsOnCollisionCourse: z.boolean(),
    actorsHaveLowTcpa: z.boolean(),
    rightOfStartStateByActorId: z.record(z.string(), z.boolean()),
    leftOfStartStateByActorId: z.record(z.string(), z.boolean()),
    haveBeenInRightManeuverByActorId: z.record(z.string(), z.boolean()),
    haveBeenInLeftManeuverByActorId: z.record(z.string(), z.boolean()),
    passedPotentialCollisionDomainByActorId: z.record(z.string(), z.boolean()),
    inFrontOfPotentialCollisionDomainByActorId: z.record(z.string(), z.boolean()),
  })
  .passthrough();

const ruleEvaluationSchema = z
  .object({
    ruleName: z.string(),
    title: z.string(),
    ruleNumber: z.string(),
    kind: z.enum(["rule", "suggestion"]),
    description: z.string(),
    subjectActorId: z.string().nullable(),
    subjectActorName: z.string(),
    result: z.enum(["PASSED", "FAILED", "UNKNOWN"]),
  })
  .passthrough();

const ruleResultSchema = z
  .object({
    relationId: z.string(),
    evaluations: z.array(ruleEvaluationSchema),
    failedRules: z.array(z.string()),
    overallStatus: z.enum(["FAILED", "NOT_FAILED"]),
  })
  .passthrough();

const maneuverStateSchema = z
  .object({
    actorId: z.string(),
    relationId: z.string().optional(),
    maneuverType: z.string(),
    previousManeuverType: z.string(),
    suggestedManeuvers: z.array(z.string()),
    maneuverCount: z.number(),
    distanceMade: z.number(),
    totalDistanceMade: z.number(),
    timespan: z.number(),
    headingChangeDirection: z.string(),
    headingDiffSincePreviousDeg: z.number(),
    headingDiffSinceStartDeg: z.number(),
    headingDiffSinceReadilyApparentDeg: z.number(),
    speedDiffSincePrevious: z.number().optional(),
    speedDiffSinceStart: z.number().optional(),
    speedDiffSinceReadilyApparent: z.number().optional(),
    startTimestamp: z.number(),
    currentTimestamp: z.number(),
    justStarted: z.boolean(),
    readilyApparentTimePassed: z.boolean(),
  })
  .passthrough();

const metricsSchema = z
  .object({
    distanceByRelationId: z.record(z.string(), z.number()).optional(),
    dcpaByRelationId: z.record(z.string(), z.number()).optional(),
    tcpaByRelationId: z.record(z.string(), z.number()).optional(),
    dsIndexByRelationId: z.record(z.string(), z.number()).optional(),
  })
  .passthrough();

const frameSchema = z
  .object({
    timestamp: z.number(),
    timeStep: z.number().positive(),
    actors: z.array(actorSchema),
    statesByActorId: z.record(z.string(), stateSchema),
    trajectoriesByActorId: z.record(z.string(), z.array(stateSchema)).optional(),
    situationContexts: z.array(situationContextSchema).default([]),
    colregsStates: z.array(colregsStateSchema).default([]),
    ruleResults: z.array(ruleResultSchema).default([]),
    maneuverStates: z.array(maneuverStateSchema).default([]),
    metrics: metricsSchema.optional(),
  })
  .passthrough();

export function parseFrame(raw: unknown): SimulationFrame {
  return frameSchema.parse(normalizeFramePayload(raw));
}

function normalizeFramePayload(raw: unknown): unknown {
  if (typeof raw !== "object" || raw === null) {
    return raw;
  }

  const frame = raw as Record<string, unknown>;

  const normalizedActors = Array.isArray(frame.actors)
    ? frame.actors.map((actor) => {
        if (typeof actor !== "object" || actor === null) {
          return actor;
        }
        const a = actor as Record<string, unknown>;
        const safetyRadius =
          typeof a.safetyRadius === "number"
            ? a.safetyRadius
            : typeof a.safety_radius === "number"
              ? a.safety_radius
              : typeof a.radius === "number"
                ? a.radius
                : 0;
        const thrusterMass =
          typeof a.thrusterMass === "number"
            ? a.thrusterMass
            : typeof a.thrustersMass === "number"
              ? a.thrustersMass
              : undefined;
        return {
          ...a,
          safetyRadius,
          ...(thrusterMass !== undefined ? { thrusterMass } : {}),
        };
      })
    : frame.actors;

  const normalizedSituationContexts = Array.isArray(frame.situationContexts)
    ? frame.situationContexts.map((ctx) => {
        if (typeof ctx !== "object" || ctx === null) {
          return ctx;
        }
        const c = ctx as Record<string, unknown>;
        return {
          ...c,
          timeSpentInCurrentContext: c.timeSpentInCurrentContext ?? 0,
          isGiveWayByActorId: c.isGiveWayByActorId ?? c.giveWayByActorId ?? {},
        };
      })
    : frame.situationContexts;

  const normalizedColregsStates = Array.isArray(frame.colregsStates)
    ? frame.colregsStates.map((state) => {
        if (typeof state !== "object" || state === null) {
          return state;
        }
        const s = state as Record<string, unknown>;
        return {
          ...s,
          rightOfStartStateByActorId:
            s.rightOfStartStateByActorId ?? s.actorsRightOfStartStateById ?? {},
          leftOfStartStateByActorId:
            s.leftOfStartStateByActorId ?? s.actorsLeftOfStartStateById ?? {},
          haveBeenInRightManeuverByActorId:
            s.haveBeenInRightManeuverByActorId ?? s.actorsHaveBeenInRightManeuverById ?? {},
          haveBeenInLeftManeuverByActorId:
            s.haveBeenInLeftManeuverByActorId ?? s.actorsHaveBeenInLeftManeuverById ?? {},
          passedPotentialCollisionDomainByActorId:
            s.passedPotentialCollisionDomainByActorId ??
            s.actorsPassedPotentialCollisionDomainById ??
            {},
          inFrontOfPotentialCollisionDomainByActorId:
            s.inFrontOfPotentialCollisionDomainByActorId ??
            s.actorsInFrontOfPotentialCollisionDomainById ??
            {},
        };
      })
    : frame.colregsStates;

  const normalizedRuleResults = Array.isArray(frame.ruleResults)
    ? frame.ruleResults.map((result) => {
        if (typeof result !== "object" || result === null) {
          return result;
        }
        const r = result as Record<string, unknown>;
        const rawEvaluations = Array.isArray(r.evaluations)
          ? r.evaluations
          : Array.isArray(r.rules)
            ? r.rules
            : [];
        const evaluations = rawEvaluations.map((evaluation) => {
          if (typeof evaluation !== "object" || evaluation === null) {
            return evaluation;
          }
          const e = evaluation as Record<string, unknown>;
          const ruleName = (e.ruleName ?? e.name ?? "Unknown Rule") as string;
          const ruleNumber = ((e.ruleNumber as string | undefined) ||
            ruleName.match(/^Rule\s+([^:]+):/i)?.[1] ||
            "") as string;
          const kind =
            e.kind === "suggestion" || e.kind === "rule"
              ? e.kind
              : ruleNumber === "" || /^suggestion:/i.test(ruleName)
                ? "suggestion"
                : "rule";
          const title =
            (e.title as string | undefined) ??
            ruleName.replace(/^(Rule\s+[^:]+|Suggestion):\s*/i, "");
          const subjectActorIdRaw = e.subjectActorId ?? e.subject_actor_id ?? null;
          return {
            ...e,
            ruleName,
            title,
            ruleNumber,
            kind,
            subjectActorId:
              subjectActorIdRaw === null || subjectActorIdRaw === undefined
                ? null
                : String(subjectActorIdRaw),
            subjectActorName: (e.subjectActorName ?? e.subject_actor_name ?? "") as string,
          };
        });
        return {
          ...r,
          evaluations,
          failedRules: r.failedRules ?? r.failedRuleNames ?? [],
          overallStatus:
            r.overallStatus ??
            ((r.isFailed as boolean | undefined) ? "FAILED" : "NOT_FAILED"),
        };
      })
    : frame.ruleResults;

  const normalizedManeuverStates = Array.isArray(frame.maneuverStates)
    ? frame.maneuverStates.map((state) => {
        if (typeof state !== "object" || state === null) {
          return state;
        }
        const s = state as Record<string, unknown>;
        const relationId = typeof s.relationId === "string" ? s.relationId : "";
        const actorIdFromRelation = relationId.includes("->")
          ? relationId.split("->")[0]
          : relationId;
        const headingChange =
          typeof s.headingChange === "object" && s.headingChange !== null
            ? (s.headingChange as Record<string, unknown>)
            : {};
        const speedChange =
          typeof s.speedChange === "object" && s.speedChange !== null
            ? (s.speedChange as Record<string, unknown>)
            : {};
        const speedPrev = s.speedDiffSincePrevious ?? speedChange.speedDiffSincePrevious;
        const speedStart = s.speedDiffSinceStart ?? speedChange.speedDiffSinceStart;
        const speedRa =
          s.speedDiffSinceReadilyApparent ?? speedChange.speedDiffSinceReadilyApparentTime;
        return {
          ...s,
          actorId: s.actorId ?? actorIdFromRelation ?? "",
          ...(relationId ? { relationId } : {}),
          previousManeuverType: s.previousManeuverType ?? s.maneuverType ?? "UNDETECTED",
          suggestedManeuvers: s.suggestedManeuvers ?? [],
          headingChangeDirection:
            s.headingChangeDirection ?? headingChange.detectedDirection ?? "none",
          headingDiffSincePreviousDeg:
            s.headingDiffSincePreviousDeg ?? headingChange.headingDiffSincePreviousDeg ?? 0,
          headingDiffSinceStartDeg:
            s.headingDiffSinceStartDeg ?? headingChange.headingDiffSinceStartDeg ?? 0,
          headingDiffSinceReadilyApparentDeg:
            s.headingDiffSinceReadilyApparentDeg ??
            headingChange.headingDiffSinceReadilyApparentTimeDeg ??
            0,
          ...(speedPrev !== undefined ? { speedDiffSincePrevious: speedPrev } : {}),
          ...(speedStart !== undefined ? { speedDiffSinceStart: speedStart } : {}),
          ...(speedRa !== undefined ? { speedDiffSinceReadilyApparent: speedRa } : {}),
        };
      })
    : frame.maneuverStates;

  const normalizedMetrics = (() => {
    if (typeof frame.metrics !== "object" || frame.metrics === null) {
      return frame.metrics;
    }
    const metrics = frame.metrics as Record<string, unknown>;
    const relations =
      typeof metrics.relations === "object" && metrics.relations !== null
        ? (metrics.relations as Record<string, unknown>)
        : null;
    if (!relations) {
      return metrics;
    }

    const distanceByRelationId: Record<string, number> = {};
    const dcpaByRelationId: Record<string, number> = {};
    const tcpaByRelationId: Record<string, number> = {};
    const dsIndexByRelationId: Record<string, number> = {};

    for (const [relationId, rawRelationMetrics] of Object.entries(relations)) {
      if (typeof rawRelationMetrics !== "object" || rawRelationMetrics === null) {
        continue;
      }
      const relationMetrics = rawRelationMetrics as Record<string, unknown>;
      if (typeof relationMetrics.distance === "number") {
        distanceByRelationId[relationId] = relationMetrics.distance;
      }
      if (typeof relationMetrics.dcpa === "number") {
        dcpaByRelationId[relationId] = relationMetrics.dcpa;
      }
      if (typeof relationMetrics.tcpa === "number") {
        tcpaByRelationId[relationId] = relationMetrics.tcpa;
      }
      if (typeof relationMetrics.dangerSector === "number") {
        dsIndexByRelationId[relationId] = relationMetrics.dangerSector;
      } else if (typeof relationMetrics.proximityIndex === "number") {
        dsIndexByRelationId[relationId] = relationMetrics.proximityIndex;
      }
    }

    return {
      ...metrics,
      distanceByRelationId:
        metrics.distanceByRelationId ?? (Object.keys(distanceByRelationId).length ? distanceByRelationId : undefined),
      dcpaByRelationId:
        metrics.dcpaByRelationId ?? (Object.keys(dcpaByRelationId).length ? dcpaByRelationId : undefined),
      tcpaByRelationId:
        metrics.tcpaByRelationId ?? (Object.keys(tcpaByRelationId).length ? tcpaByRelationId : undefined),
      dsIndexByRelationId:
        metrics.dsIndexByRelationId ?? (Object.keys(dsIndexByRelationId).length ? dsIndexByRelationId : undefined),
    };
  })();

  return {
    ...frame,
    actors: normalizedActors,
    situationContexts: normalizedSituationContexts,
    colregsStates: normalizedColregsStates,
    ruleResults: normalizedRuleResults,
    maneuverStates: normalizedManeuverStates,
    metrics: normalizedMetrics,
  };
}

export type ParsedServerMessage =
  | {
      kind: "initial_state";
      scenarioId: string | null;
      timeStep: number | null;
      totalTrajectoryLength: number | null;
    }
  | {
      kind: "preview_trajectory_chunk";
      scenarioId: string | null;
      fromTimestamp: number;
      toTimestamp: number;
      frames: SimulationFrame[];
    }
  | {
      kind: "simulation_trajectory_chunk";
      scenarioId: string | null;
      fromTimestamp: number;
      toTimestamp: number;
      frames: SimulationFrame[];
    }
  | { kind: "frame"; frame: SimulationFrame }
  | { kind: "error"; message: string }
  | { kind: "ack"; action: string }
  | {
      kind: "generated_scene";
      requestId: string | null;
      valid: boolean;
      scene: SimulationFrame;
      evaluationData: EvaluationData | null;
    }
  | {
      kind: "trajectory_generation_preview";
      requestId: string | null;
      trajectoryData: Record<string, unknown>;
    }
  | {
      kind: "trajectory_generation_result";
      requestId: string | null;
      trajectoryData: Record<string, unknown> | null;
      valid: boolean;
      errorMessage: string | null;
    }
  | {
      kind: "simulation_status";
      status:
        | "running"
        | "starting"
        | "ready to start"
        | "agents are preparing"
        | "initializing"
        | "not initialized"
        | "offline";
    }
  | { kind: "waraps_status"; status: "connected" | "disconnected" }
  | { kind: "monitor_status"; status: "connected" | "disconnected" }
  | {
      kind: "simulation_models";
      /** Per-vessel SDF model content keyed by the same id used in connectionsByAgentId. */
      vesselModelsByAgentId: Record<string, string | null>;
    }
  | { kind: "unknown"; raw: unknown };

const initialStateSchema = z.object({
  type: z.literal("initial_state"),
  scenarioId: z.string().optional().nullable(),
  timeStep: z.number().positive().optional().nullable(),
  totalTrajectoryLength: z.number().nonnegative().optional().nullable(),
});

const previewTrajectoryChunkSchema = z.object({
  type: z.literal("preview_trajectory_chunk"),
  scenarioId: z.string().optional().nullable(),
  fromTimestamp: z.number(),
  toTimestamp: z.number(),
  frames: z.array(z.unknown()),
});

const simulationTrajectoryChunkSchema = z.object({
  type: z.literal("simulation_trajectory_chunk"),
  scenarioId: z.string().optional().nullable(),
  fromTimestamp: z.number(),
  toTimestamp: z.number(),
  frames: z.array(z.unknown()),
});

const generatedSceneSchema = z.object({
  type: z.literal("generated_scene"),
  requestId: z.string().optional().nullable(),
  valid: z.boolean().optional().default(false),
  scene: z.unknown(),
  evaluationData: z.record(z.string(), z.unknown()).optional().nullable(),
});

const errorSchema = z.object({
  type: z.literal("error"),
  message: z.string(),
});

const ackSchema = z.object({
  type: z.literal("ack"),
  action: z.string(),
});

const warapsStatusSchema = z.object({
  type: z.literal("waraps_status"),
  status: z.enum(["connected", "disconnected"]),
});

const monitorStatusSchema = z.object({
  type: z.literal("monitor_status"),
  status: z.enum(["connected", "disconnected"]),
});

const simulationModelsConnectionSchema = z
  .object({
    gazeboVesselModel: z.string().optional().nullable(),
  })
  .passthrough();

const simulationModelsSchema = z.object({
  type: z.literal("simulation_models"),
  connectionsByAgentId: z
    .record(z.string(), simulationModelsConnectionSchema)
    .optional()
    .default({}),
});

const simulationStatusSchema = z.object({
  type: z.literal("simulation_status"),
  status: z.enum([
    "running",
    "starting",
    "ready to start",
    "agents are preparing",
    "initializing",
    "not initialized",
    "offline",
  ]),
});

const framePushSchema = z
  .object({
    type: z.literal("frame"),
  })
  .and(frameSchema);

export function parseServerMessage(raw: unknown): ParsedServerMessage {
  if (typeof raw !== "object" || raw === null) {
    return { kind: "frame", frame: parseFrame(raw) };
  }
  const obj = raw as Record<string, unknown>;
  if (typeof obj.type !== "string") {
    return { kind: "frame", frame: parseFrame(raw) };
  }

  const msgType = typeof obj.type === "string" ? obj.type : "";
  const payload = (obj.payload as Record<string, unknown> | undefined) ?? obj;

  if (msgType === "initial_state") {
    const initialCandidate = {
      type: "initial_state" as const,
      scenarioId: payload.scenarioId ?? payload.scenario_id ?? null,
      timeStep: payload.timeStep ?? payload.time_step ?? null,
      totalTrajectoryLength:
        payload.totalTrajectoryLength ??
        payload.total_trajectory_length ??
        payload.trajectoryLength ??
        payload.trajectory_length ??
        payload.totalLength ??
        payload.total_length ??
        null,
    };
    const parsed = initialStateSchema.parse(initialCandidate);
    return {
      kind: "initial_state",
      scenarioId: parsed.scenarioId ?? null,
      timeStep: parsed.timeStep ?? null,
      totalTrajectoryLength: parsed.totalTrajectoryLength ?? null,
    };
  }
  if (msgType === "preview_trajectory_chunk") {
    const chunkCandidate = {
      type: "preview_trajectory_chunk" as const,
      scenarioId: payload.scenarioId ?? payload.scenario_id ?? null,
      fromTimestamp: payload.fromTimestamp ?? payload.from_timestamp ?? 0,
      toTimestamp:
        payload.toTimestamp ??
        payload.to_timestamp ??
        payload.timestamp ??
        payload.upToTimestamp ??
        payload.up_to_timestamp ??
        0,
      frames: payload.frames ?? [],
    };
    const parsed = previewTrajectoryChunkSchema.parse(chunkCandidate);
    return {
      kind: "preview_trajectory_chunk",
      scenarioId: parsed.scenarioId ?? null,
      fromTimestamp: parsed.fromTimestamp,
      toTimestamp: parsed.toTimestamp,
      frames: parsed.frames.map((frame) => parseFrame(frame)),
    };
  }
  if (msgType === "simulation_trajectory_chunk") {
    const chunkCandidate = {
      type: "simulation_trajectory_chunk" as const,
      scenarioId: payload.scenarioId ?? payload.scenario_id ?? null,
      fromTimestamp: payload.fromTimestamp ?? payload.from_timestamp ?? 0,
      toTimestamp:
        payload.toTimestamp ??
        payload.to_timestamp ??
        payload.timestamp ??
        payload.upToTimestamp ??
        payload.up_to_timestamp ??
        0,
      frames: payload.frames ?? [],
    };
    const parsed = simulationTrajectoryChunkSchema.parse(chunkCandidate);
    return {
      kind: "simulation_trajectory_chunk",
      scenarioId: parsed.scenarioId ?? null,
      fromTimestamp: parsed.fromTimestamp,
      toTimestamp: parsed.toTimestamp,
      frames: parsed.frames.map((frame) => parseFrame(frame)),
    };
  }
  if (msgType === "generated_scene") {
    const rawEvaluationData = payload.evaluationData ?? payload.evaluation_data ?? null;
    const sceneCandidate = {
      type: "generated_scene" as const,
      requestId: payload.requestId ?? payload.request_id ?? null,
      valid: payload.valid ?? false,
      scene: payload.scene ?? payload.frame ?? payload.snapshot ?? null,
      evaluationData:
        typeof rawEvaluationData === "object" &&
        rawEvaluationData !== null &&
        !Array.isArray(rawEvaluationData)
          ? rawEvaluationData
          : null,
    };
    const parsed = generatedSceneSchema.parse(sceneCandidate);
    return {
      kind: "generated_scene",
      requestId: parsed.requestId ?? null,
      valid: parsed.valid,
      scene: parseFrame(parsed.scene),
      evaluationData: parsed.evaluationData ?? null,
    };
  }
  if (msgType === "trajectory_generation_preview") {
    const trajectoryData = payload.trajectoryData ?? payload.trajectory_data ?? {};
    return {
      kind: "trajectory_generation_preview",
      requestId: (payload.requestId ?? payload.request_id ?? null) as string | null,
      trajectoryData:
        typeof trajectoryData === "object" && trajectoryData !== null
          ? (trajectoryData as Record<string, unknown>)
          : {},
    };
  }
  if (msgType === "trajectory_generation_result") {
    const trajectoryData = payload.trajectoryData ?? payload.trajectory_data ?? null;
    return {
      kind: "trajectory_generation_result",
      requestId: (payload.requestId ?? payload.request_id ?? null) as string | null,
      trajectoryData:
        typeof trajectoryData === "object" && trajectoryData !== null
          ? (trajectoryData as Record<string, unknown>)
          : null,
      valid: Boolean(payload.valid ?? false),
      errorMessage: (payload.errorMessage ?? payload.error_message ?? null) as string | null,
    };
  }
  if (msgType === "frame") {
    const parsed = framePushSchema.parse(raw);
    const { type: _type, ...rest } = parsed;
    void _type;
    return { kind: "frame", frame: parseFrame(rest) };
  }
  if (msgType === "error") {
    return { kind: "error", message: errorSchema.parse(raw).message };
  }
  if (msgType === "ack") {
    return { kind: "ack", action: ackSchema.parse(raw).action };
  }
  if (msgType === "waraps_status") {
    return {
      kind: "waraps_status",
      status: warapsStatusSchema.parse(raw).status,
    };
  }
  if (msgType === "monitor_status") {
    return {
      kind: "monitor_status",
      status: monitorStatusSchema.parse(raw).status,
    };
  }
  if (msgType === "simulation_models") {
    const parsed = simulationModelsSchema.parse({
      type: "simulation_models" as const,
      connectionsByAgentId:
        payload.connectionsByAgentId ?? payload.connections_by_agent_id ?? {},
    });
    const vesselModelsByAgentId: Record<string, string | null> = {};
    for (const [agentId, connection] of Object.entries(parsed.connectionsByAgentId)) {
      const c = connection as Record<string, unknown>;
      const model =
        typeof c.gazeboVesselModel === "string"
          ? c.gazeboVesselModel
          : typeof c.gazebo_vessel_model === "string"
            ? (c.gazebo_vessel_model as string)
            : null;
      vesselModelsByAgentId[agentId] = model;
    }
    return {
      kind: "simulation_models",
      vesselModelsByAgentId,
    };
  }
  if (msgType === "simulation_status") {
    return {
      kind: "simulation_status",
      status: simulationStatusSchema.parse({
        type: "simulation_status",
        status: payload.status ?? obj.status,
      }).status,
    };
  }

  return { kind: "unknown", raw };
}
