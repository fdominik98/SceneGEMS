import { describe, expect, it } from "vitest";
import { outputRowSchema } from "../../../domain/cluster/historyApi";
import { artifactRefSchema } from "../../../domain/cluster/schemas";
import { sampleArtifactRef, sampleDroppedOutput, sampleSceneOutput, sampleSimulationOutput, sampleTrajectoryOutput } from "../../../test/fixtures/historyViews";
import { baseName, configRefOf, itemFromOutput, itemFromUpload, outputProblem, outputUsable, sameOutput, scenarioFromUpload, uniqueName, uploadHoursLeft, uploadNote } from "./inputItems";
import { fileProblem } from "./useArtifactUpload";
import { UPLOAD_LIFETIME_MS } from "./wizardState";

const SCENE = outputRowSchema.parse(sampleSceneOutput());
const TRAJECTORY = outputRowSchema.parse(sampleTrajectoryOutput());
const RUN = outputRowSchema.parse(sampleSimulationOutput());
const DROPPED = outputRowSchema.parse(sampleDroppedOutput());
const NOW = 1_800_000_000_000;

describe("names", () => {
  it("takes the file name without folder and extension", () => {
    expect(baseName("C:\\scenes\\head_on.json")).toBe("head_on");
    expect(baseName("a/b/two.parts.problem")).toBe("two.parts");
    expect(baseName(".hidden")).toBe(".hidden");
  });

  it("numbers a name that is taken", () => {
    expect(uniqueName("scene", [])).toBe("scene");
    expect(uniqueName("scene", ["scene"])).toBe("scene 2");
    expect(uniqueName("scene", ["scene", "scene 2"])).toBe("scene 3");
  });
});

describe("artifact references", () => {
  it("writes a reference without a null pointer and keeps a pointer that is set", () => {
    const plain = configRefOf(artifactRefSchema.parse(sampleArtifactRef()));
    expect(plain).toEqual({ sha256: expect.any(String), size_bytes: 20480, kind: "scene", media_type: "application/json" });
    expect(plain).not.toHaveProperty("pointer");
    expect(configRefOf(artifactRefSchema.parse(sampleArtifactRef({ kind: "trajectory_data", pointer: "/trajectories" }))).pointer).toBe("/trajectories");
  });
});

describe("items from outputs", () => {
  it("makes an item of a usable output with its source and a name from the entry and the case", () => {
    const made = itemFromOutput("Head-on", "c1", "scene_generation", SCENE, ["scene"], []);
    expect(made).toMatchObject({
      name: `Head-on case ${SCENE.case_index}`,
      source: { campaign_id: "c1", case_id: SCENE.case_id, step: "scene_generation" },
      ref: { kind: "scene" },
      uploadedAt: null,
    });
  });

  it("keeps the pointer of trajectory data and numbers the run of a simulation output", () => {
    const planned = itemFromOutput("Plan", "c1", "trajectory_generation", TRAJECTORY, ["trajectory_data", "trajectories"], []);
    expect(planned?.ref).toMatchObject({ kind: "trajectory_data", pointer: "/trajectories" });
    const run = itemFromOutput("Sim", "c2", "simulation", RUN, ["trajectory_data", "trajectories"], []);
    expect(run?.name).toBe(`Sim case ${RUN.case_index} run 1`);
    expect(run?.ref.kind).toBe("trajectories");
  });

  it("gives a second item of the same name a number", () => {
    expect(itemFromOutput("Head-on", "c1", "scene_generation", SCENE, ["scene"], [`Head-on case ${SCENE.case_index}`])?.name).toBe(`Head-on case ${SCENE.case_index} 2`);
  });

  it("refuses outputs that are dropped, invalid or of another kind, and says why", () => {
    expect(outputUsable(DROPPED, ["scene"])).toBe(false);
    expect(outputProblem(DROPPED, ["scene"])).toBe("scene is not valid");
    expect(itemFromOutput("x", "c1", "scene_generation", DROPPED, ["scene"], [])).toBeNull();
    expect(outputProblem(SCENE, ["trajectory_data"])).toBe("a scene, not usable here");
    expect(outputProblem({ ...SCENE, valid: false }, ["scene"])).toBe("not valid");
    expect(outputProblem(SCENE, ["scene"])).toBeNull();
    expect(outputProblem({ ...SCENE, artifact: null, reason: null }, ["scene"])).toBe("no output");
  });

  it("knows an output that is an item already", () => {
    const made = itemFromOutput("Head-on", "c1", "scene_generation", SCENE, ["scene"], []);
    expect(made).not.toBeNull();
    if (made) {
      expect(sameOutput(made, "c1", "scene_generation", SCENE)).toBe(true);
      expect(sameOutput(made, "c2", "scene_generation", SCENE)).toBe(false);
      expect(sameOutput(made, "c1", "scene_generation", { ...SCENE, case_id: SCENE.case_id + 1 })).toBe(false);
      expect(sameOutput({ ...made, source: { file: "f.json" } }, "c1", "scene_generation", SCENE)).toBe(false);
    }
  });
});

describe("items from uploads", () => {
  const ref = artifactRefSchema.parse(sampleArtifactRef({ kind: "scene" }));

  it("makes an item named after the file with the file as its source", () => {
    const made = itemFromUpload("head_on.json", ref, ["other"], NOW);
    expect(made).toMatchObject({ name: "head_on", source: { file: "head_on.json" }, uploadedAt: NOW, ref: { kind: "scene" } });
  });

  it("makes a scenario with quota 1 and failure budget 0, a name without a slash and a name of its own", () => {
    const functional = artifactRefSchema.parse(sampleArtifactRef({ kind: "functional_scenario", media_type: "text/plain" }));
    const made = scenarioFromUpload("my_head_on.problem", functional, ["my_head_on"], NOW);
    expect(made).toMatchObject({ name: "my_head_on 2", fileName: "my_head_on.problem", quota: 1, failureBudget: 0, uploadedAt: NOW });
    expect(scenarioFromUpload("a/b.problem", functional, [], NOW).name).toBe("b");
  });
});

describe("upload expiry notes", () => {
  it("counts the hours left, rounding up, and zero once gone", () => {
    expect(uploadHoursLeft(NOW, NOW)).toBe(24);
    expect(uploadHoursLeft(NOW - UPLOAD_LIFETIME_MS + 1000, NOW)).toBe(1);
    expect(uploadHoursLeft(NOW - UPLOAD_LIFETIME_MS, NOW)).toBe(0);
    expect(uploadHoursLeft(null, NOW)).toBeNull();
    // A clock that was read before the upload never shows more than the 24 hours
    expect(uploadHoursLeft(NOW + 5000, NOW)).toBe(24);
  });

  it("says when the control node deletes an upload and that history outputs are kept", () => {
    expect(uploadNote(NOW, NOW)).toContain("about 24 hours unless a campaign uses it");
    expect(uploadNote(NOW - UPLOAD_LIFETIME_MS + 1000, NOW)).toContain("about 1 hour ");
    expect(uploadNote(NOW - UPLOAD_LIFETIME_MS, NOW)).toContain("Expired");
    expect(uploadNote(null, NOW)).toContain("Kept by the control node");
  });
});

describe("fileProblem", () => {
  it("refuses an empty file and, for scenes and trajectories, anything that is not JSON", () => {
    expect(fileProblem("  ", "scene")).toBe("The file is empty.");
    expect(fileProblem("{not json", "scene")).toBe("The file is not valid JSON.");
    expect(fileProblem("{\"a\": 1}", "trajectories")).toBeNull();
  });

  it("takes any text as a functional scenario", () => {
    expect(fileProblem("problem p { }", "functional_scenario")).toBeNull();
  });
});
