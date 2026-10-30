import { describe, expect, it } from "vitest";
import { catalogStacksSchema, type CatalogClass } from "../../../domain/cluster/campaignApi";
import { nodeViewSchema } from "../../../domain/cluster/schemas";
import { sampleCatalogClasses, sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { sampleNode } from "../../../test/fixtures/clusterViews";
import { needLabel, type RequiredCapability, type ResourcePlan } from "../resourcePlan";
import { buildCampaignMap, CARD_WIDTH, drawingOffset, plannedCases, reviewStatusOf, STAGE_HEIGHT, type MapContext, type MapFact } from "./campaignMapModel";
import { emptyDraft, emptyRun, WIZARD_STEPS, type InputItemDraft, type WizardDraft, type WizardStepId } from "./wizardState";

const stacks = catalogStacksSchema.parse(sampleCatalogStacks);
const classes: CatalogClass[] = sampleCatalogClasses;
const NO_PROBLEMS = Object.fromEntries(WIZARD_STEPS.map((step) => [step, 0])) as Record<WizardStepId, number>;

function context(overrides: Partial<MapContext> = {}): MapContext {
  return { stacks, classes, plan: null, problems: NO_PROBLEMS, runProblems: [], review: "unchecked", ...overrides };
}

function draftOf(change: (draft: WizardDraft) => void = () => undefined): WizardDraft {
  const draft = emptyDraft();
  draft.name = "sweep";
  draft.runs = [{ ...emptyRun("kinematic.replay"), id: "r1" }];
  change(draft);
  return draft;
}

function item(id: string, source: InputItemDraft["source"]): InputItemDraft {
  return { id, name: id, ref: { sha256: "b".repeat(64), size_bytes: 10, kind: "scene" }, source, uploadedAt: null };
}

const texts = (facts: readonly MapFact[]) => facts.map((fact) => fact.text);

describe("the chain of the map", () => {
  it("draws the whole chain left to right with arrows from the input to the review", () => {
    const map = buildCampaignMap(draftOf(), context());
    expect(map.cards.map((card) => [card.id, card.kind, card.page])).toEqual([
      ["input", "input", "input"],
      ["scene_generation", "stage", "scenes"],
      ["trajectory_generation", "stage", "trajectories"],
      ["run:r1", "run", "runs"],
      ["review", "review", "review"],
    ]);
    expect(map.edges.map((edge) => edge.id)).toEqual(["input->scene_generation", "scene_generation->trajectory_generation", "trajectory_generation->run:r1", "run:r1->review"]);
    const xs = map.cards.map((card) => card.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(map.width).toBe(Math.max(...map.cards.map((card) => card.x + card.width)));
  });

  it("puts the runs in a simulation frame, fanning out from the step before and into the review", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.runs = [
          { ...emptyRun("kinematic.replay"), id: "r1" },
          { ...emptyRun("kinematic.usv_navigation"), id: "r2" },
        ];
      }),
      context()
    );
    expect(map.edges.map((edge) => edge.id)).toEqual(expect.arrayContaining(["trajectory_generation->run:r1", "trajectory_generation->run:r2", "run:r1->review", "run:r2->review"]));
    const [frame] = map.frames;
    expect(frame.title).toBe("Simulation, 2 runs");
    const runs = map.cards.filter((card) => card.kind === "run");
    for (const run of runs) {
      expect(run.x).toBeGreaterThan(frame.x);
      expect(run.x + run.width).toBeLessThan(frame.x + frame.width);
      expect(run.y).toBeGreaterThan(frame.y);
      expect(run.y + run.height).toBeLessThanOrEqual(frame.y + frame.height);
    }
    expect(runs[1].y).toBeGreaterThan(runs[0].y + runs[0].height);
    // The frame sets the drawing's height; the other cards sit in its middle
    expect(map.height).toBe(frame.height);
    const input = map.cards.find((card) => card.id === "input");
    expect(input?.y).toBe((map.height - STAGE_HEIGHT) / 2);
  });

  it("draws the steps a later start skips before the input and the steps an early stop leaves after the review", () => {
    const later = buildCampaignMap(draftOf((draft) => void (draft.steps = ["trajectory_generation"])), context());
    expect(later.cards.map((card) => card.id)).toEqual(["skipped:scene_generation", "input", "trajectory_generation", "review", "skipped:simulation"]);
    expect(later.edges.map((edge) => edge.id)).toEqual(["input->trajectory_generation", "trajectory_generation->review"]);
    const skipped = later.cards.filter((card) => card.kind === "skipped");
    expect(skipped.map((card) => [card.page, texts(card.facts)])).toEqual([
      ["steps", ["Not run"]],
      ["steps", ["Not run"]],
    ]);
    expect(later.frames).toEqual([]);
    expect(later.height).toBe(STAGE_HEIGHT);
  });

  it("reports the problems of each page on its cards and of each run on its own card", () => {
    const problems = { ...NO_PROBLEMS, input: 2, scenes: 1, runs: 3, steps: 1, resources: 4 };
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.runs = [
          { ...emptyRun("kinematic.replay"), id: "r1" },
          { ...emptyRun(""), id: "r2" },
        ];
      }),
      context({ problems, runProblems: [0, 3] })
    );
    const count = (id: string) => map.cards.find((card) => card.id === id)?.problems;
    expect([count("input"), count("scene_generation"), count("trajectory_generation"), count("run:r1"), count("run:r2"), count("review")]).toEqual([2, 1, 0, 0, 3, 0]);
    expect(map.settings.map((setting) => [setting.id, setting.problems])).toEqual([
      ["steps", 1],
      ["domain", 0],
      ["resources", 4],
      ["policy", 0],
    ]);
  });
});

describe("what the cards say", () => {
  it("counts the catalog's FECs and the cases of the quotas, or what was named while the catalog is not loaded", () => {
    const draft = draftOf((next) => {
      next.scope = [{ id: "s", classes: ["4vessel_0obstacle_scenarios/functional_model1"], patterns: ["2vessel_0obstacle_*"], quota: 2, failureBudget: 0 }];
    });
    const input = (map: ReturnType<typeof buildCampaignMap>) => map.cards.find((card) => card.id === "input");
    expect(texts(input(buildCampaignMap(draft, context()))?.facts ?? [])).toEqual(["4 FECs of the catalog", "8 cases to complete"]);
    expect(texts(input(buildCampaignMap(draft, context({ classes: undefined })))?.facts ?? [])).toEqual(["1 FEC, 1 pattern"]);
    expect(plannedCases(draft, classes)).toBe(8);
    expect(plannedCases(draft, undefined)).toBeNull();
  });

  it("asks for input while nothing is chosen, and counts scenario files and items by source", () => {
    const empty = buildCampaignMap(draftOf(), context()).cards[0];
    expect(empty.facts).toEqual([{ text: "Nothing chosen yet", tone: "warn" }]);

    const withFile = draftOf((draft) => {
      draft.input.scenarios = [{ id: "f", fileName: "a.problem", name: "a", ref: { sha256: "c".repeat(64), size_bytes: 1, kind: "functional_scenario" }, quota: 3, failureBudget: 0, uploadedAt: 0 }];
    });
    expect(texts(buildCampaignMap(withFile, context()).cards[0].facts)).toEqual(["1 scenario file", "3 cases to complete"]);

    const scenes = draftOf((draft) => {
      draft.steps = ["trajectory_generation", "simulation"];
      draft.input.items = [item("a", { campaign_id: "c1", case_id: 1, step: "scene_generation" }), item("b", { campaign_id: "c1", case_id: 2, step: "scene_generation" }), item("c", { file: "c.json" })];
    });
    const input = buildCampaignMap(scenes, context()).cards.find((card) => card.id === "input");
    expect(texts(input?.facts ?? [])).toEqual(["3 scenes", "2 from Campaign History, 1 file"]);
  });

  it("says the monitor and the settings of each generation step", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.sceneMonitor = "post_hoc";
        draft.domain.enforceLowTcpa = true;
        draft.trajectories.parameters = { max_iterations: 100 };
      }),
      context()
    );
    expect(texts(map.cards[1].facts)).toEqual(["Post hoc monitor", "At most 60 s per scene", "Low TCPA enforced"]);
    expect(texts(map.cards[2].facts)).toEqual(["Monitor driven RRT", "1 parameter changed", "No monitor"]);

    const unknown = buildCampaignMap(draftOf((draft) => void (draft.trajectories.generator = "unheard_of")), context());
    expect(unknown.cards[2].facts[0]).toEqual({ text: "unheard_of", tone: "bad" });
  });

  it("names each run by its name, stack, monitor and repeats", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.runs = [
          { ...emptyRun("kinematic.usv_navigation", "live"), id: "r1", name: "controller", repeats: 3, earlyStop: true },
          { ...emptyRun("", "empty"), id: "r2" },
        ];
      }),
      context()
    );
    const runs = map.cards.filter((card) => card.kind === "run");
    expect(runs.map((card) => [card.title, ...texts(card.facts)])).toEqual([
      ["Run 1: controller", "USV Navigation on the kinematic layer", "Live monitor, 3 repeats, early stop"],
      ["Run 2", "No stack chosen", "No monitor"],
    ]);
    expect(runs[1].facts[0].tone).toBe("warn");
  });

  it("states the master's check and the work planned on the review card", () => {
    const draft = draftOf((next) => {
      next.scope = [{ id: "s", classes: ["3vessel_0obstacle_scenarios/functional_model1"], patterns: [], quota: 3, failureBudget: 0 }];
      next.runs = [
        { ...emptyRun("kinematic.replay"), id: "r1" },
        { ...emptyRun("kinematic.replay"), id: "r2", repeats: 2 },
      ];
    });
    const review = buildCampaignMap(draft, context({ review: "accepted" })).cards.find((card) => card.id === "review");
    expect(review?.facts).toEqual([
      { text: "Accepted by the master", tone: "ok" },
      { text: "3 cases, 9 simulations", tone: "muted" },
    ]);
    const scenesOnly = buildCampaignMap({ ...draft, steps: ["scene_generation"] }, context({ review: "refused" })).cards.find((card) => card.id === "review");
    expect(texts(scenesOnly?.facts ?? [])).toEqual(["Refused by the master", "3 cases planned"]);
  });
});

describe("the settings of the whole campaign", () => {
  const KINEMATIC_RUNS: RequiredCapability = { jobType: "simulation", components: ["asv_software/replay", "control_layer/none", "simulation_layer/kinematic"], stage: "simulate", reason: "the runs" };
  const GAZEBO_RUNS: RequiredCapability = { jobType: "simulation", components: ["asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo"], stage: "simulate", reason: "the runs" };
  const plan = (missing: RequiredCapability[]): ResourcePlan => ({
    required: [],
    coverage: [],
    missing,
    usable: [nodeViewSchema.parse(sampleNode())],
    unknownNodes: [],
  });

  it("says the name and the chain, the domain, the machines and the policy", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.steps = ["trajectory_generation", "simulation"];
        draft.domain.custom = true;
        draft.policy.seed = 7;
        draft.policy.maxCases = 100;
      }),
      context({ plan: plan([]) })
    );
    expect(map.settings.map((setting) => [setting.page, ...texts(setting.facts)])).toEqual([
      ["steps", "sweep", "Trajectory generation to simulation"],
      ["domain", "Customized for this campaign"],
      ["resources", "Every machine, full capacity", "1 machine usable"],
      ["policy", "Keep everything, base seed 7", "1 stop condition"],
    ]);
  });

  it("warns about a missing name and machines the campaign cannot start without", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.name = " ";
        draft.steps = ["scene_generation"];
      }),
      context({ plan: plan([KINEMATIC_RUNS, GAZEBO_RUNS]) })
    );
    const [steps, , resources] = map.settings;
    expect(steps.facts).toEqual([
      { text: "No name yet", tone: "warn" },
      { text: "Scene generation only", tone: "muted" },
    ]);
    const first = needLabel(KINEMATIC_RUNS); // the resources step's name of the need, with the components the runs need
    expect(first.startsWith("simulation with ")).toBe(true);
    expect(resources.facts).toEqual([{ text: `Missing: S${first.slice(1)} and 1 more`, tone: "bad" }]);
  });

  it("says the machines are not read yet without a plan", () => {
    const map = buildCampaignMap(
      draftOf((draft) => {
        draft.resources.fullUsage = false;
        draft.resources.nodes = ["a", "b"];
      }),
      context()
    );
    expect(texts(map.settings[2].facts)).toEqual(["2 machines chosen", "Machines not read yet"]);
  });
});

describe("reviewStatusOf", () => {
  const yaml = "format: 3\n";

  it("waits for the browser's own problems, then follows the master's answer to the current config", () => {
    expect(reviewStatusOf(2, { status: "valid", yaml }, yaml)).toBe("incomplete");
    expect(reviewStatusOf(0, { status: "idle", yaml: null }, yaml)).toBe("unchecked");
    expect(reviewStatusOf(0, { status: "checking", yaml }, yaml)).toBe("checking");
    expect(reviewStatusOf(0, { status: "valid", yaml }, yaml)).toBe("accepted");
    expect(reviewStatusOf(0, { status: "invalid", yaml }, yaml)).toBe("refused");
    expect(reviewStatusOf(0, { status: "error", yaml }, yaml)).toBe("failed");
  });

  it("treats an answer to an older config as not checked", () => {
    expect(reviewStatusOf(0, { status: "valid", yaml: "format: 2\n" }, yaml)).toBe("unchecked");
  });
});

describe("drawingOffset", () => {
  it("centers a drawing that fits", () => {
    expect(drawingOffset(1000, 600, 1, null, 16)).toBe(200);
  });

  it("starts a wider drawing at its left end while the page's cards are in view", () => {
    expect(drawingOffset(800, 1000, 0.7, null, 16)).toBe(16);
    expect(drawingOffset(800, 1000, 0.7, 400, 16)).toBe(16);
  });

  it("brings cards further right to the right edge, never past the drawing's end", () => {
    // The cards end at 1400 * 0.7 = 980 in the canvas and are moved to end at 800 - 16 = 784
    expect(drawingOffset(800, 1000, 0.7, 1400, 16)).toBeCloseTo(784 - 980);
    expect(drawingOffset(800, 1000, 0.7, 1500, 16)).toBe(800 - 16 - 1000);
  });
});

describe("card sizes", () => {
  it("keeps every card of a step as wide as the others", () => {
    const map = buildCampaignMap(draftOf(), context());
    expect(new Set(map.cards.map((card) => card.width))).toEqual(new Set([CARD_WIDTH]));
  });
});
