import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { useClusterRunStore } from "../cluster/clusterRunStore";
import type { ClusterRunPlan } from "../cluster/simulationJobs";
import type { JobTypeResources } from "../cluster/workbenchResources";
import { SimulationRunPanel } from "./SimulationRunPanel";
import type { SimulationStreamControls } from "./types";

const initialPlayback = usePlaybackStore.getState();
const initialRun = useClusterRunStore.getState();

/** A scenario of the own ship (id 0, on Mission Planner by default) and one target, as the backend numbers them. */
function twoVessels(): SimulationFrame {
  const base = sampleFrames[0]!;
  const own = base.actors.find((actor) => actor.isOwnShip)!;
  const target = base.actors.find((actor) => !actor.isOwnShip)!;
  const state = Object.values(base.statesByActorId)[0]!;
  return {
    ...base,
    actors: [
      { ...own, id: "0", name: "os" },
      { ...target, id: "1", name: "ts1" },
    ],
    statesByActorId: { 0: state, 1: { ...state, x: state.x + 500 } },
  };
}

function controls() {
  const resources = (jobType: string, components: readonly string[] = []): JobTypeResources => ({ jobType, components: [...components], workerNodes: 1, slots: 2, freeSlots: 2, blocker: null });
  return {
    sendMessage: vi.fn(),
    clusterResources: vi.fn(resources),
    operatorClient: null,
    runSimulationOnCluster: vi.fn(),
    stopSimulationOnCluster: vi.fn(),
    startSimulationOnCluster: vi.fn(),
    setClusterRunSpeed: vi.fn(),
    setSpeed: vi.fn(),
  };
}

function renderPanel(streamControls: ReturnType<typeof controls>) {
  render(<SimulationRunPanel streamControls={streamControls as unknown as SimulationStreamControls} colregsConstraintsContent="rules: []" />);
}

function loadScenario() {
  usePlaybackStore.getState().setTrajectoryPreviewFrames([twoVessels()]);
  usePlaybackStore.setState({ simulationInitialized: true });
}

beforeEach(() => {
  usePlaybackStore.setState(initialPlayback, true);
  useClusterRunStore.setState(initialRun, true);
});

describe("SimulationRunPanel", () => {
  it("has nothing to run before a scenario is loaded, and offers no session of its own", () => {
    renderPanel(controls());
    expect(screen.getByText("No input yet")).toBeInTheDocument();
    expect(screen.getByText("Take the input trajectories to set up the vessels.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run on the cluster" })).toBeDisabled();
    for (const name of ["Initialize", "Start", "Reset", "Connect"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("runs a setup no unattended runner takes as an attended job on the cluster", async () => {
    const user = userEvent.setup();
    const streamControls = controls();
    loadScenario();
    renderPanel(streamControls);
    expect(screen.getByText(/waits for your Start/)).toBeInTheDocument();
    expect(screen.getByText(/2 slots on 1 machine, 2 free/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Run on the cluster" }));
    expect(streamControls.runSimulationOnCluster).toHaveBeenCalledTimes(1);
    const [plan, constraints] = streamControls.runSimulationOnCluster.mock.calls[0] as unknown as [ClusterRunPlan, string];
    expect(plan).toMatchObject({ where: "cluster", jobType: "simulation", runner: "attended" });
    expect(constraints).toBe("rules: []");
    expect(streamControls.sendMessage).not.toHaveBeenCalledWith(expect.objectContaining({ type: "initialize_simulation" }));
  });

  it("does not submit a setup no job runs, and says what to change", async () => {
    const user = userEvent.setup();
    const streamControls = controls();
    loadScenario();
    renderPanel(streamControls);
    // A Gazebo world steps with ArduPilot or with the custom controller: the own ship stays on ArduPilot
    await user.selectOptions(screen.getByRole("combobox", { name: "Control layer of ts1, target ship" }), "custom");
    expect(screen.getByText("Cannot run")).toBeInTheDocument();
    expect(screen.getByText(/No job runs this setup as it is/)).toBeInTheDocument();
    expect(screen.getByText(/now os on ArduPilot, ts1 on Custom/)).toBeInTheDocument();
    expect(screen.queryByText(/waits for your Start/)).toBeNull();
    const runButton = screen.getByRole("button", { name: "Run on the cluster" });
    expect(runButton).toBeDisabled();
    expect(runButton).toHaveAttribute("title", expect.stringContaining("either with ArduPilot or with the custom controller"));

    await user.selectOptions(screen.getByRole("combobox", { name: "Control layer of ts1, target ship" }), "ardupilot");
    expect(screen.queryByText("Cannot run")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Run on the cluster" }));
    expect(streamControls.runSimulationOnCluster).toHaveBeenCalledTimes(1);
  });

  it("gives the operator the Start of an attended job once its vessels are up", async () => {
    const user = userEvent.setup();
    const streamControls = controls();
    loadScenario();
    useClusterRunStore.setState({ status: "running", jobId: "job-1", workerNodeId: "worker-node-a1", phase: "preparing" });
    renderPanel(streamControls);
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Run on the cluster" })).toBeNull();

    useClusterRunStore.setState({ phase: "ready_to_start" });
    expect(await screen.findByText("Ready to start")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start" }));
    expect(streamControls.startSimulationOnCluster).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(streamControls.stopSimulationOnCluster).toHaveBeenCalledTimes(1);
  });
});
