import type { PipelineResult } from "./types";

export function batchIsComplete(result: PipelineResult): boolean {
  const used = result.nesting.sheet_outcomes.filter(
    (s) => s.placed_parts.length > 0,
  );
  return (
    result.nesting.total_requested > 0 &&
    result.nesting.total_placed === result.nesting.total_requested &&
    used.reduce((count, sheet) => count + sheet.placed_parts.length, 0) ===
      result.nesting.total_placed &&
    result.nesting.unplaced_instances.length === 0 &&
    result.nesting.sanitizer_verified &&
    used.length > 0 &&
    result.gcode_programs.every((p) => p.verification.verified_safe) &&
    used.every((sheet) =>
      result.gcode_programs.some(
        (p) => p.sheet_id === sheet.sheet_id && p.verification.verified_safe,
      ),
    )
  );
}
