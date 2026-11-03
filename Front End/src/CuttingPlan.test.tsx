import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CuttingPlan } from "./CuttingPlan";
import { downloadText } from "./api";
import raw from "../public/example/recording.json";
import type { PipelineResult } from "./types";
vi.mock("./api", () => ({ downloadText: vi.fn() }));
describe("sheet-specific artifacts", () => {
  it("shows no generated program when no parts fit", () => {
    const result = structuredClone(raw.result) as unknown as PipelineResult;
    result.nesting.total_requested = 1;
    result.nesting.total_placed = 0;
    result.nesting.unplaced_instances = ["DXF_1_001"];
    result.nesting.sheet_outcomes = [];
    result.gcode_programs = [];
    result.metrics.sheets_used = 0;
    result.metrics.usable_area_utilization_pct = 0;
    render(<CuttingPlan result={result} example={false} committed={false} busy="" onCommit={() => {}} />);
    expect(screen.getByText("No cutting program generated · no stock updated.")).not.toBeNull();
    expect(screen.queryByText(/^Verified program/)).toBeNull();
    expect(screen.getByRole("button", { name: "Download G-code" }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "Record completed cut" })).toBeNull();
    expect(screen.getByText("No fit found", { exact: true })).not.toBeNull();
    expect(screen.getByRole("tab", { name: /Sheet 1/ })).not.toBeNull();
    // A rejected placement still shows the actual stock, rather than a blank canvas.
    expect(screen.getByText(/Inspect remnant/)).not.toBeNull();
  });
  it("explains failed remnants, supports inspecting each, and keeps partial orders uncommitted", async () => {
    const result = structuredClone(raw.result) as unknown as PipelineResult;
    result.nesting.total_requested = result.nesting.total_placed + 1;
    result.nesting.unplaced_instances = ["CUSTOM_002"];
    const stock = result.candidate_sheets[0];
    result.candidate_sheets.unshift({ ...stock, sheet_id: "TOO_SMALL", usable_area_mm2: 10 });
    result.nesting.placement_checks = [{
      sheet_id: "TOO_SMALL", part_id: "CUSTOM", width_mm: 60, height_mm: 40,
      requested: 2, placed: 0, remaining: 2, reason: "INSUFFICIENT_AREA",
      message: "One part needs 24.0 cm² of material; this remnant has only 0.1 cm².",
      next_step: "Choose a larger remnant, or check the drawing's size and units.",
    }];
    render(<CuttingPlan result={result} example={false} committed={false} busy="" onCommit={() => {}} />);
    expect(screen.getByText("Partial fit", { exact: true })).not.toBeNull();
    expect(screen.getByText(/One part needs 24.0 cm²/)).not.toBeNull();
    expect(screen.getByText(/Choose a larger remnant/)).not.toBeNull();
    expect(screen.getByRole("button", { name: "Download G-code" }).hasAttribute("disabled")).toBe(true);
    await userEvent.click(screen.getByRole("tab", { name: /Sheet 1/ }));
    expect(screen.getByText(/Inspect remnant/).textContent).toContain("TOO_SMALL");
    expect(screen.getByRole("button", { name: "Inspect planned path" }).hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "Record completed cut" })).toBeNull();
  });
  it("switches the geometry and download to the selected sheet", async () => {
    const result = structuredClone(raw.result) as unknown as PipelineResult;
    result.plan_id = "two-sheet-saved-plan";
    const original = result.nesting.sheet_outcomes[0];
    result.nesting.sheet_outcomes.push({
      ...original,
      sheet_id: "SECOND_SHEET",
    });
    result.candidate_sheets.push({
      ...result.candidate_sheets[0],
      sheet_id: "SECOND_SHEET",
    });
    result.candidate_sheets.push({ ...result.candidate_sheets[0], sheet_id: "UNUSED_STOCK" });
    result.gcode_programs.push({
      ...result.gcode_programs[0],
      sheet_id: "SECOND_SHEET",
      gcode_text: "SECOND SHEET VERIFIED FIXTURE",
    });
    result.nesting.total_placed *= 2;
    result.nesting.total_requested *= 2;
    result.metrics.sheets_used = 2;
    render(
      <CuttingPlan
        result={result}
        example={false}
        committed={false}
        busy=""
        onCommit={() => {}}
      />,
    );
    expect(screen.getByText("Stock order · smallest usable remnant first")).not.toBeNull();
    const allocation = document.querySelector(".stock-allocation")!;
    expect(allocation.textContent).toContain("still needed");
    expect(allocation.textContent).toContain("SECOND_SHEET");
    await userEvent.click(screen.getByRole("tab", { name: /Sheet 2/ }));
    await userEvent.click(
      screen.getByRole("button", { name: "Download G-code" }),
    );
    expect(downloadText).toHaveBeenCalledWith(
      "SECOND SHEET VERIFIED FIXTURE",
      "SECOND_SHEET.nc",
    );
    await userEvent.click(screen.getByRole("tab", { name: /Sheet 3/ }));
    expect(screen.getByText(/Inspect remnant/).textContent).toContain("UNUSED_STOCK");
    expect(screen.getByText("Not used in this plan · no cutting program for this remnant.")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Download G-code" }).hasAttribute("disabled")).toBe(true);
  });
});
