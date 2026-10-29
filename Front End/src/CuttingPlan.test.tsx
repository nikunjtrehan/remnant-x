import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CuttingPlan } from "./CuttingPlan";
import { downloadText } from "./api";
import raw from "../public/example/recording.json";
import type { PipelineResult } from "./types";
vi.mock("./api", () => ({ downloadText: vi.fn() }));
describe("sheet-specific artifacts", () => {
  it("switches the geometry and download to the selected sheet", async () => {
    const result = structuredClone(raw.result) as unknown as PipelineResult;
    const original = result.nesting.sheet_outcomes[0];
    result.nesting.sheet_outcomes.push({
      ...original,
      sheet_id: "SECOND_SHEET",
    });
    result.candidate_sheets.push({
      ...result.candidate_sheets[0],
      sheet_id: "SECOND_SHEET",
    });
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
    await userEvent.click(screen.getByRole("tab", { name: /Sheet 2/ }));
    await userEvent.click(
      screen.getByRole("button", { name: "Download G-code" }),
    );
    expect(downloadText).toHaveBeenCalledWith(
      "SECOND SHEET VERIFIED FIXTURE",
      "SECOND_SHEET.nc",
    );
  });
});
