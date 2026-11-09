import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RunDuration } from "./EntryDetail";

describe("RunDuration", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts up each second while the entry runs", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-28T10:00:10Z"));
    render(
      <p data-testid="duration">
        <RunDuration startedAt="2026-10-28T10:00:00Z" finishedAt={null} prefix="ran for " />
      </p>
    );
    expect(screen.getByTestId("duration")).toHaveTextContent("ran for 10 s");
    act(() => vi.advanceTimersByTime(5_000));
    expect(screen.getByTestId("duration")).toHaveTextContent("ran for 15 s");
  });

  it("keeps no clock for a finished entry", () => {
    vi.useFakeTimers();
    render(
      <p data-testid="duration">
        <RunDuration startedAt="2026-10-28T10:00:00Z" finishedAt="2026-10-28T10:01:30Z" />
      </p>
    );
    expect(screen.getByTestId("duration")).toHaveTextContent("1 min 30 s");
    expect(vi.getTimerCount()).toBe(0);
  });
});
