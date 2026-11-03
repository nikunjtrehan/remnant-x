import { describe, expect, it } from "vitest";
import { errorGuidance } from "./errors";

describe("order parsing recovery guidance", () => {
  it.each(["ERR_MODEL_ORDER_JSON", "ERR_UNPARSED_ORDER", "ERR_MODEL_CHANGED_MATERIAL_GRADE"])("explains %s with a usable next step", code => {
    const guidance = errorGuidance(code);
    expect(guidance.body).toContain("Build parts list");
    expect(guidance.body).toContain("inventory has not changed");
    expect(guidance.body).not.toContain(code);
    expect(guidance.detail).toBe(code);
  });
});
