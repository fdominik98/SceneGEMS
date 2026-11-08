import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_STRAIGHT_TIMESPAN,
  DEFAULT_TRAJECTORY_GENERATOR,
  TRAJECTORY_GENERATION_PARAM_DEFAULTS,
  TRAJECTORY_GENERATORS,
  toParamsWire,
  useTrajectoryGenerationStore,
} from "./trajectoryGenerationStore";

describe("trajectory generator selection", () => {
  beforeEach(() => {
    useTrajectoryGenerationStore.setState({
      generator: DEFAULT_TRAJECTORY_GENERATOR,
      timespan: DEFAULT_STRAIGHT_TIMESPAN,
      params: { ...TRAJECTORY_GENERATION_PARAM_DEFAULTS },
      status: "idle",
      activeRequestId: null,
      resultScenarioJson: null,
      resultValid: false,
      resultComplete: null,
      errorMessage: null,
    });
  });

  it("offers the monitor-guided planner first and the straight generator", () => {
    expect(TRAJECTORY_GENERATORS).toEqual([
      { id: "monitor_driven_rrt", label: "Monitor-guided planner" },
      { id: "straight", label: "Straight" },
    ]);
  });

  it("defaults to the planner and a one hour timespan", () => {
    const state = useTrajectoryGenerationStore.getState();
    expect(state.generator).toBe("monitor_driven_rrt");
    expect(state.timespan).toBe(3600);
  });

  it("keeps the chosen generator and timespan", () => {
    const { setGenerator, setTimespan } = useTrajectoryGenerationStore.getState();
    setGenerator("straight");
    setTimespan(600);
    const state = useTrajectoryGenerationStore.getState();
    expect(state.generator).toBe("straight");
    expect(state.timespan).toBe(600);
  });

  it("leaves the planner parameters alone when the generator changes or the parameters reset", () => {
    const { setGenerator, setParam, resetParams } = useTrajectoryGenerationStore.getState();
    setParam("timeout", 42);
    setGenerator("straight");
    expect(useTrajectoryGenerationStore.getState().params.timeout).toBe(42);
    resetParams();
    expect(useTrajectoryGenerationStore.getState().params.timeout).toBe(
      TRAJECTORY_GENERATION_PARAM_DEFAULTS.timeout
    );
    expect(useTrajectoryGenerationStore.getState().generator).toBe("straight");
  });

  it("records whether the result is a complete plan, and forgets it on a new run", () => {
    const { markResult, startRun } = useTrajectoryGenerationStore.getState();
    markResult({ valid: true, complete: false, scenarioJson: "{}", errorMessage: null });
    expect(useTrajectoryGenerationStore.getState().resultComplete).toBe(false);
    startRun("r2");
    expect(useTrajectoryGenerationStore.getState().resultComplete).toBeNull();
    markResult({ valid: true, complete: true, scenarioJson: "{}", errorMessage: null });
    expect(useTrajectoryGenerationStore.getState().resultComplete).toBe(true);
  });

  it("leaves complete unknown when the backend does not send it", () => {
    useTrajectoryGenerationStore
      .getState()
      .markResult({ valid: true, scenarioJson: "{}", errorMessage: null });
    expect(useTrajectoryGenerationStore.getState().resultComplete).toBeNull();
  });
});

describe("toParamsWire", () => {
  const params = { ...TRAJECTORY_GENERATION_PARAM_DEFAULTS, timeStep: 10 };

  it("sends the planner with every tuning value by default", () => {
    expect(toParamsWire(params)).toEqual({
      generator: "monitor_driven_rrt",
      timeStep: 10,
      timeout: 300,
      maxIterations: 2000,
      directionThreshold: 1,
      bestRandomNodesK: 20,
      previewInterval: 1,
      includeMonitorResults: true,
    });
  });

  it("carries the monitor results switch for the planner", () => {
    expect(toParamsWire(params, false, "monitor_driven_rrt").includeMonitorResults).toBe(false);
  });

  it("sends no timespan with the planner", () => {
    expect("timespan" in toParamsWire(params, true, "monitor_driven_rrt", 600)).toBe(false);
  });

  it("sends only the generator, the step and the timespan for the straight generator", () => {
    expect(toParamsWire(params, true, "straight", 600)).toEqual({
      generator: "straight",
      timeStep: 10,
      timespan: 600,
    });
  });

  it("defaults the straight timespan to one hour", () => {
    expect(toParamsWire(params, true, "straight").timespan).toBe(3600);
  });
});
