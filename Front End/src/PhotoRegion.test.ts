import { describe, expect, it } from "vitest";
import { normalizedBox } from "./PhotoRegion";
describe("SAM box coordinates", () => {
  it("normalizes reverse drags and clamps exclusive bounds in the rectified image", () => {
    expect(normalizedBox([401.2, 301.3], [-3, -7], 400, 300)).toEqual([
      0, 0, 400, 300,
    ]);
    expect(normalizedBox([90.4, 80.5], [10.2, 20.7], 400, 300)).toEqual([
      10, 20, 91, 81,
    ]);
  });
  it("rejects accidental clicks and tiny drags", () => {
    expect(normalizedBox([10, 20], [12, 22], 400, 300)).toBeNull();
  });
});
