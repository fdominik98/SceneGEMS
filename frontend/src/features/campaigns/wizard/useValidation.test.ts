import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
import { validationFromError } from "./useValidation";

describe("validationFromError", () => {
  it("parses the reasons of a refused config", () => {
    const error = new OperatorApiError("http", "the campaign config is not valid", "/cluster/campaigns/validate", 422, [
      "scope.0: the pattern 'x' matches no class",
      "execution.runs.0.stack.dt: Input should be greater than 0",
    ]);
    const state = validationFromError("name: x\n", error);
    expect(state.status).toBe("invalid");
    expect(state.yaml).toBe("name: x\n");
    expect(state.reasons.map((reason) => [reason.step, reason.entry, reason.field])).toEqual([
      ["input", 0, null],
      ["runs", 0, "stack.dt"],
    ]);
  });

  it("uses the message when a 422 comes without reasons", () => {
    const state = validationFromError("x", new OperatorApiError("http", "the request is not valid", "/p", 422));
    expect(state.reasons).toHaveLength(1);
    expect(state.reasons[0].message).toBe("the request is not valid");
  });

  it("reports an unreachable control node or another status as a failed check, not as reasons", () => {
    const unreachable = validationFromError("x", new OperatorApiError("network", "cannot reach http://127.0.0.1:5174 (Failed to fetch)", "/p"));
    expect(unreachable).toMatchObject({ status: "error", reasons: [] });
    expect(unreachable.message).toContain("cannot reach");
    expect(validationFromError("x", new OperatorApiError("http", "unsupported", "/p", 415)).status).toBe("error");
    expect(validationFromError("x", new OperatorApiError("schema", "unexpected answer from /p", "/p", 200, ["valid: Invalid input"])).status).toBe("error");
  });
});
