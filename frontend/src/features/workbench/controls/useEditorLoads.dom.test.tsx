import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useEditorLoads, type EditorLoad } from "./useEditorLoads";

/** A load the test finishes by hand. */
function deferred() {
  let resolve: (value: EditorLoad | null) => void = () => undefined;
  let reject: (error: Error) => void = () => undefined;
  const promise = new Promise<EditorLoad | null>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function setup() {
  const apply = vi.fn();
  const fail = vi.fn();
  const hook = renderHook(() => useEditorLoads(apply, fail));
  return { apply, fail, hook };
}

describe("useEditorLoads", () => {
  it("names the pick while it loads, then applies it", async () => {
    const { apply, hook } = setup();
    const first = deferred();
    act(() => hook.result.current.load("1vessel_0obstacle_scenarios/functional_model0", () => first.promise, "failed"));
    expect(hook.result.current.pending).toEqual({ label: "1vessel_0obstacle_scenarios/functional_model0" });
    await act(async () => first.resolve({ label: "1vessel_0obstacle_scenarios/functional_model0", text: "OS(os1).\n" }));
    expect(apply).toHaveBeenCalledWith({ label: "1vessel_0obstacle_scenarios/functional_model0", text: "OS(os1).\n" });
    expect(hook.result.current.pending).toBeNull();
  });

  it("applies only the latest of two loads, whatever order they end in", async () => {
    const { apply, hook } = setup();
    const older = deferred();
    const newer = deferred();
    act(() => hook.result.current.load("a", () => older.promise, "failed"));
    act(() => hook.result.current.load("b", () => newer.promise, "failed"));
    await act(async () => newer.resolve({ label: "b", text: "B" }));
    await act(async () => older.resolve({ label: "a", text: "A" }));
    expect(apply.mock.calls).toEqual([[{ label: "b", text: "B" }]]);
    expect(hook.result.current.pending).toBeNull();
  });

  it("drops a running load when the operator types", async () => {
    const { apply, hook } = setup();
    const running = deferred();
    act(() => hook.result.current.load("a", () => running.promise, "failed"));
    act(() => hook.result.current.cancel());
    expect(hook.result.current.pending).toBeNull();
    await act(async () => running.resolve({ label: "a", text: "A" }));
    expect(apply).not.toHaveBeenCalled();
  });

  it("reports a failed load with its reason, and a stale failure not at all", async () => {
    const { fail, hook } = setup();
    const stale = deferred();
    const current = deferred();
    act(() => hook.result.current.load("a", () => stale.promise, "The functional scenario could not be loaded"));
    act(() => hook.result.current.load("b", () => current.promise, "The functional scenario could not be loaded"));
    await act(async () => stale.reject(new Error("HTTP 404")));
    expect(fail).not.toHaveBeenCalled();
    await act(async () => current.reject(new Error("HTTP 503")));
    expect(fail).toHaveBeenCalledWith("The functional scenario could not be loaded: HTTP 503");
    expect(hook.result.current.pending).toBeNull();
  });
});
