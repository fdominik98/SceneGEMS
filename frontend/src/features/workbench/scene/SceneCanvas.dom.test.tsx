import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { PlaybackStoreContext } from "../../../domain/playback/playbackContext";
import { createPlaybackStore } from "../../../domain/playback/playbackStore";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { SceneCanvas } from "./SceneCanvas";

class StubResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", StubResizeObserver);
});

afterAll(() => {
  vi.unstubAllGlobals();
});

const initialUi = useUiStore.getState();

beforeEach(() => {
  useUiStore.setState(initialUi, true);
  useUiStore.setState({ sceneViewMode: "cartesian", rightPaneVisible: true });
});

function renderCanvas() {
  const store = createPlaybackStore();
  store.getState().setTrajectoryPreviewFrames(sampleFrames.slice(0, 5));
  render(
    <PlaybackStoreContext.Provider value={store}>
      <SceneCanvas />
    </PlaybackStoreContext.Provider>
  );
  return store;
}

describe("SceneCanvas", () => {
  it("has icon buttons for the view: fit, orientation, layers, export and the map", () => {
    renderCanvas();
    for (const name of ["Fit view", "Head up", "Layers", "Export", "Show nautical map"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("title");
    }
    expect(screen.queryByRole("button", { name: /^View options/ })).not.toBeInTheDocument();
  });

  it("shows the button that brings the monitoring panel back only while the panel is hidden", async () => {
    const user = userEvent.setup();
    renderCanvas();
    expect(screen.queryByRole("button", { name: "Show monitoring panel" })).not.toBeInTheDocument();

    act(() => useUiStore.getState().setRightPaneVisible(false));
    await user.click(screen.getByRole("button", { name: "Show monitoring panel" }));
    expect(useUiStore.getState().rightPaneVisible).toBe(true);
    expect(screen.queryByRole("button", { name: "Show monitoring panel" })).not.toBeInTheDocument();
  });

  it("sets the preview's layers, and the simulation's beside them once it sent frames", async () => {
    const user = userEvent.setup();
    const store = renderCanvas();
    await user.click(screen.getByRole("button", { name: "Layers" }));

    await user.click(screen.getByRole("checkbox", { name: "Course vectors" }));
    expect(useUiStore.getState().previewOverlays.velocity).toBe(false);
    await user.click(screen.getByRole("checkbox", { name: "Visible" }));
    expect(useUiStore.getState().hidePreviewStream).toBe(true);

    act(() => store.getState().ingestSimulationFrames(sampleFrames.slice(0, 5)));
    await user.click(screen.getByRole("checkbox", { name: "Tracks, Simulation" }));
    expect(useUiStore.getState().simulationOverlays.trajectory).toBe(false);
    expect(useUiStore.getState().previewOverlays.trajectory).toBe(true);
    await user.click(screen.getByRole("checkbox", { name: "Simulation visible" }));
    expect(useUiStore.getState().hideSimulationStream).toBe(true);
  });

  it("switches between the encounter canvas and the nautical map", async () => {
    const user = userEvent.setup();
    renderCanvas();
    await user.click(screen.getByRole("button", { name: "Show nautical map" }));
    expect(useUiStore.getState().sceneViewMode).toBe("nautical");
    expect(screen.queryByRole("button", { name: "Head up" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Layers" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show encounter canvas" }));
    expect(useUiStore.getState().sceneViewMode).toBe("cartesian");
  });
});
