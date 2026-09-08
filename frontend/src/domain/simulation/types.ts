export type RuleResult = "PASSED" | "FAILED" | "UNKNOWN";
export type OverallStatus = "FAILED" | "NOT_FAILED";

export interface ActorStaticInfo {
  id: string;
  name: string;
  isVessel: boolean;
  isOwnShip: boolean;
  type: string;
  length: number;
  breadth: number;
  /** Former wire field `radius`; server now sends `safetyRadius`. */
  safetyRadius: number;
  height?: number;
  draft?: number;
  mass?: number;
  maxSpeed?: number;
  maxAngularSpeed?: number;
  maxAcceleration?: number;
  /** Present on serialized `ConcreteVessel` actors. */
  rudderMass?: number;
  rudderLength?: number;
  rudderWidth?: number;
  rudderHeight?: number;
  propellerDiameter?: number;
  thrusterMass?: number;
  motorLength?: number;
}

export interface ActorKinematicState {
  x: number;
  y: number;
  speed: number;
  heading: number;
}

/**
 * Parametric description of a COLREGS safety domain. The backend sends shape
 * parameters rather than a polygon (see `_safety_domain_payload` in
 * `backend/src/scenegems_tool/backend_service/serialization.py`); the canvas draws
 * the curve. `radius` is set for circles, `a`/`b` for ellipses and rectangles.
 */
export interface SafetyDomainShape {
  shape: "circle" | "ellipse" | "rectangle";
  center: [number, number];
  heading: number;
  radius?: number;
  a?: number;
  b?: number;
}

/** One circle of a static avoidance domain (a frozen potential collision domain). */
export interface StaticAvoidanceDomain {
  center: [number, number];
  radius: number;
}

export interface SituationContextData {
  relationId: string;
  actor1Id: string;
  actor2Id: string;
  situationType: string;
  situationLabel: string;
  startTimestamp: number;
  timeSpentInCurrentContext: number;
  avoidanceDirectionByActorId: Record<string, string>;
  isGiveWayByActorId: Record<string, boolean>;
  globalAvoidanceDirectionByActorId: Record<string, string>;
  /**
   * The side the rules actually judge each actor against, fixed when the encounter
   * began. The two fields above are recomputed per scene, so they can differ once a
   * concurrent encounter ends. Absent on older payloads.
   */
  effectiveAvoidanceDirectionByActorId?: Record<string, string>;
  globalGiveWayByActorId: Record<string, boolean>;
  /** Safety domain each actor must keep clear in this encounter. Absent on older payloads. */
  safetyDomainsByActorId?: Record<string, SafetyDomainShape>;
  /** Domains frozen when the encounter started, which each actor has to go around. */
  staticAvoidanceDomainsByActorId?: Record<string, StaticAvoidanceDomain[]>;
}

export interface ColregsMonitorStateData {
  relationId: string;
  actorsSeeEachOther: boolean;
  actorsPassedEachOther: boolean;
  actorsViolateSafetyDomain: boolean;
  actorsOnCollisionCourse: boolean;
  actorsHaveLowTcpa: boolean;
  rightOfStartStateByActorId: Record<string, boolean>;
  leftOfStartStateByActorId: Record<string, boolean>;
  haveBeenInRightManeuverByActorId: Record<string, boolean>;
  haveBeenInLeftManeuverByActorId: Record<string, boolean>;
  passedPotentialCollisionDomainByActorId: Record<string, boolean>;
  inFrontOfPotentialCollisionDomainByActorId: Record<string, boolean>;
}

export type RuleKind = "rule" | "suggestion";

export interface RuleEvaluation {
  /** Full display label, e.g. "Rule 16: Give-Way Vessel Takes Early and Substantial Action". */
  ruleName: string;
  /** Short title without the rule-number prefix. */
  title: string;
  /** COLREGS rule number ("8", "16", "17"); empty for advisory suggestions. */
  ruleNumber: string;
  /** "rule" (a compliance failure matters) or "suggestion" (advisory only). */
  kind: RuleKind;
  description: string;
  /** Id of the vessel the rule constrains, or null when it applies to the encounter. */
  subjectActorId: string | null;
  /** Display name of the subject vessel, e.g. "OS_0"; empty when encounter-scoped. */
  subjectActorName: string;
  result: RuleResult;
}

export interface RuleResultData {
  relationId: string;
  evaluations: RuleEvaluation[];
  failedRules: string[];
  overallStatus: OverallStatus;
}

export interface ManeuverStateData {
  actorId: string;
  /** Relation this maneuver state was monitored under, e.g. "0->1". */
  relationId?: string;
  maneuverType: string;
  previousManeuverType: string;
  suggestedManeuvers: string[];
  maneuverCount: number;
  distanceMade: number;
  totalDistanceMade: number;
  timespan: number;
  headingChangeDirection: string;
  headingDiffSincePreviousDeg: number;
  headingDiffSinceStartDeg: number;
  headingDiffSinceReadilyApparentDeg: number;
  /** Speed deltas in m/s; present when the monitor reports a speed change. */
  speedDiffSincePrevious?: number;
  speedDiffSinceStart?: number;
  speedDiffSinceReadilyApparent?: number;
  startTimestamp: number;
  currentTimestamp: number;
  justStarted: boolean;
  readilyApparentTimePassed: boolean;
}

export interface ScenarioMetrics {
  distanceByRelationId?: Record<string, number>;
  dcpaByRelationId?: Record<string, number>;
  tcpaByRelationId?: Record<string, number>;
  dsIndexByRelationId?: Record<string, number>;
  /** Raw scene-level metrics passed through from the backend serializer. */
  scene?: Record<string, number>;
  /** Raw per-relation metrics (distance, dcpa, tcpa, safetyDistance, visibilityDistance). */
  relations?: Record<string, Record<string, number>>;
}

export interface SimulationFrame {
  timestamp: number;
  timeStep: number;
  actors: ActorStaticInfo[];
  statesByActorId: Record<string, ActorKinematicState>;
  trajectoriesByActorId?: Record<string, ActorKinematicState[]>;
  situationContexts: SituationContextData[];
  colregsStates: ColregsMonitorStateData[];
  ruleResults: RuleResultData[];
  maneuverStates: ManeuverStateData[];
  metrics?: ScenarioMetrics;
}

export type EvaluationData = Record<string, unknown>;

export interface GeneratedSceneData {
  scene: SimulationFrame;
  evaluationData?: EvaluationData;
  /** Whether the generated scene complies with the functional specification. */
  valid: boolean;
}

export type SimulationCommand =
  | { command: "pause" }
  | { command: "resume" }
  | { command: "set_speed"; value: number }
  | { command: "seek"; value: number };
