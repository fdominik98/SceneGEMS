import { describe, expect, it } from "vitest";
import { artifactFileName, describeStack, formatBytes, formatSeconds, runLabel, shortClassId, shortHash, sortedArtifacts, stageLabel } from "./resultsFormat";

describe("results formatting", () => {
  it("names the stages, the last one as the monitor summary", () => {
    expect(stageLabel("generate_scene")).toBe("generate scene");
    expect(stageLabel("verdict")).toBe("monitor summary");
  });

  it("formats seconds", () => {
    expect(formatSeconds(null)).toBe("-");
    expect(formatSeconds(12.5)).toBe("12.5 s");
    expect(formatSeconds(31.2000001)).toBe("31.2 s");
    expect(formatSeconds(65)).toBe("1 min 05 s");
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KiB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MiB");
    expect(formatBytes(null)).toBe("");
  });

  it("shortens hashes and class ids", () => {
    expect(shortHash("abcdef0123456789", 6)).toBe("abcdef");
    expect(shortHash(null)).toBe("-");
    expect(shortClassId("short")).toBe("short");
    expect(shortClassId("a".repeat(60), 20)).toBe(`...${"a".repeat(17)}`);
  });

  it("labels runs and stacks", () => {
    // Counted from 1 for people.
    expect(runLabel(1, 2)).toBe("run 2, repeat 3");
    expect(runLabel(0)).toBe("run 1");
    expect(runLabel(null)).toBe("-");
    expect(describeStack({ simulation_layer: "kinematic", mode: "usv_navigation", dt: 0.1 })).toBe("kinematic usv_navigation");
    expect(describeStack({ other: 1 })).toBe('{"other":1}');
  });

  it("lists the state log and frames of a run first", () => {
    expect(sortedArtifacts({ zeta: "z", frames: "f", state_log: "s", alpha: "a" }).map(([role]) => role)).toEqual(["state_log", "frames", "alpha", "zeta"]);
  });

  it("names a downloaded artifact by its role, hash and media type", () => {
    const sha = "0123456789abcdef".repeat(4);
    expect(artifactFileName("state_log", sha, "application/json")).toBe("state_log-0123456789ab.json");
    expect(artifactFileName("frames", sha, "application/x-ndjson; charset=utf-8")).toBe("frames-0123456789ab.jsonl");
    expect(artifactFileName("report", sha, "application/vnd.x+json")).toBe("report-0123456789ab.json");
    expect(artifactFileName("blob", sha, "")).toBe("blob-0123456789ab");
  });
});
