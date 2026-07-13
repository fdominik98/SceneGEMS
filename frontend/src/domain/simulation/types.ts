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
  globalGiveWayByActorId: Record<string, boolean>;
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

export interface RuleEvaluation {
  ruleName: string;
  description: string;
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
