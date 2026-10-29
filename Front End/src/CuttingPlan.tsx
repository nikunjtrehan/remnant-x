import { useEffect, useState } from "react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  Check,
  CheckCircle2,
  FileText,
  Layers2,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";
import { SheetViewer } from "./SheetViewer";
import { downloadText } from "./api";
import { formatNumber } from "./geometry";
import { batchIsComplete } from "./verification";
import type { PipelineResult } from "./types";

export function CuttingPlan({
  result,
  example,
  committed,
  busy,
  onCommit,
}: {
  result: PipelineResult | null;
  example: boolean;
  committed: boolean;
  busy: string;
  onCommit: () => void;
}) {
  const [sheetId, setSheetId] = useState("");
  const [selectedPart, setSelectedPart] = useState("");
  const [toolpath, setToolpath] = useState(false);
  const [pathPlaying, setPathPlaying] = useState(false);
  const [pathProgress, setPathProgress] = useState<number | undefined>(
    undefined,
  );
  const [details, setDetails] = useState(false);
  const shownResult = result;
  const outcomes =
    shownResult?.nesting.sheet_outcomes.filter(
      (s) => s.placed_parts.length > 0,
    ) ?? [];
  const outcome = outcomes.find((s) => s.sheet_id === sheetId) ?? outcomes[0];
  const stock = shownResult?.candidate_sheets.find(
    (s) => s.sheet_id === outcome?.sheet_id,
  );
  const program = shownResult?.gcode_programs.find(
    (p) => p.sheet_id === outcome?.sheet_id,
  );
  useEffect(() => {
    setPathPlaying(false);
    setPathProgress(undefined);
  }, [program]);
  useEffect(() => {
    if (!pathPlaying || !program) return;
    const timer = setInterval(
      () =>
        setPathProgress((p) =>
          Math.min(program.ordered_loops.length, (p ?? 0) + 0.08),
        ),
      40,
    );
    return () => clearInterval(timer);
  }, [pathPlaying, program]);
  useEffect(() => {
    if (
      program &&
      pathProgress !== undefined &&
      pathProgress >= program.ordered_loops.length
    )
      setPathPlaying(false);
  }, [pathProgress, program]);
  const complete = shownResult ? batchIsComplete(shownResult) : false;
  useEffect(() => {
    setSheetId("");
    setSelectedPart("");
    setToolpath(false);
  }, [shownResult]);
  return (
    <div className="result-column">
      <section className="panel canvas-panel">
        <div className="canvas-heading">
          <div>
            <span className="eyebrow">
              {shownResult ? "CUTTING PLAN" : "SPATIAL WORKSPACE"}
            </span>
            <h2>
              {shownResult
                ? complete
                  ? "A useful future for this remnant."
                  : "Some parts still need a home."
                : "Room for your next idea."}
            </h2>
            {shownResult && (
              <p className="result-summary">
                {shownResult.nesting.total_placed}/
                {shownResult.nesting.total_requested} parts placed ·{" "}
                {shownResult.metrics.sheets_used} sheet
                {shownResult.metrics.sheets_used === 1 ? "" : "s"} ·{" "}
                {formatNumber(shownResult.metrics.usable_area_utilization_pct)}%
                usable area occupied
              </p>
            )}
          </div>
          <span
            className={`badge ${shownResult ? (complete ? "good" : "warn") : "neutral"}`}
          >
            {shownResult ? (
              complete ? (
                <>
                  <ShieldCheck size={12} />
                  Software verified
                </>
              ) : (
                "Partial batch"
              )
            ) : (
              "Plan view"
            )}
          </span>
        </div>
        {!!outcomes.length && (
          <div
            className="sheet-tabs"
            role="tablist"
            aria-label="Sheets in cutting plan"
          >
            {outcomes.map((s, i) => (
              <button
                key={s.sheet_id}
                role="tab"
                aria-selected={outcome?.sheet_id === s.sheet_id}
                onClick={() => {
                  setSheetId(s.sheet_id);
                  setSelectedPart("");
                }}
              >
                <Layers2 size={12} />
                Sheet {i + 1}
                <span>{s.placed_parts.length} parts</span>
              </button>
            ))}
          </div>
        )}
        <SheetViewer
          key={`${example}-${outcome?.sheet_id ?? "empty"}`}
          geometry={stock?.geometry}
          parts={outcome?.placed_parts}
          program={program}
          zone={outcome?.kerf_safe_zone}
          title="Nesting layout"
          selected={selectedPart}
          onSelect={setSelectedPart}
          toolpath={toolpath}
          pathProgress={pathProgress}
        />
        {toolpath && program && (
          <div className="playback-bar">
            <span>Planned toolpath · playback only</span>
            <button
              className="button ghost"
              onClick={() => {
                if (
                  !pathPlaying &&
                  (pathProgress === undefined ||
                    pathProgress >= program.ordered_loops.length)
                )
                  setPathProgress(0);
                setPathPlaying((v) => !v);
              }}
            >
              {pathPlaying ? <Pause size={12} /> : <Play size={12} />}{" "}
              {pathPlaying ? "Pause sequence" : "Play cut sequence"}
            </button>
            <button
              className="icon-button"
              aria-label="Reset path playback"
              onClick={() => {
                setPathPlaying(false);
                setPathProgress(undefined);
              }}
            >
              <RotateCcw size={13} />
            </button>
          </div>
        )}
        {outcome && (
          <div className="part-inspector">
            <span className="muted">Inspect a part</span>
            <select
              aria-label="Inspect placed part"
              value={selectedPart}
              onChange={(e) => setSelectedPart(e.target.value)}
            >
              <option value="">Select on the sheet or from this list</option>
              {outcome.placed_parts.map((p) => (
                <option key={p.instance_id} value={p.instance_id}>
                  {p.instance_id} · {p.rotation_deg}°
                </option>
              ))}
            </select>
          </div>
        )}
        {shownResult ? (
          <>
            <div className="metric-strip">
              <div>
                <strong>
                  {shownResult.nesting.total_placed}
                  <small> / {shownResult.nesting.total_requested}</small>
                </strong>
                <span>parts placed</span>
              </div>
              <div>
                <strong>
                  {formatNumber(
                    shownResult.metrics.usable_area_utilization_pct,
                  )}
                  <small>%</small>
                </strong>
                <span>usable area occupied</span>
              </div>
              <div>
                <strong>{shownResult.metrics.sheets_used}</strong>
                <span>
                  sheet{shownResult.metrics.sheets_used === 1 ? "" : "s"} used
                </span>
              </div>
            </div>
            <div className="action-row">
              <button
                className="button secondary"
                disabled={!program?.verification.verified_safe}
                onClick={() => {
                  if (program?.verification.verified_safe)
                    downloadText(
                      program.gcode_text,
                      `${example ? "example-" : ""}${program.sheet_id}.nc`,
                    );
                }}
              >
                <ArrowDownToLine size={14} />
                {example ? "Example G-code" : "Download G-code"}
              </button>
              <button
                className={toolpath ? "button secondary" : "button ghost"}
                aria-pressed={toolpath}
                disabled={!program}
                onClick={() => {
                  setToolpath((v) => !v);
                  setPathPlaying(false);
                  setPathProgress(undefined);
                }}
              >
                <Play size={13} />
                {toolpath ? "Hide planned path" : "Inspect planned path"}
              </button>
              <button
                className="button ghost"
                onClick={() => setDetails((v) => !v)}
              >
                <FileText size={13} />
                {details ? "Hide details" : "Verification"}
              </button>
            </div>
            <div className="canvas-caption">
              <span className="pulse-square" />
              {example
                ? "Recorded backend output · synthetic station · no live inference"
                : committed
                  ? "Predicted stock updated. This is the newly planned and verified result."
                  : "Preview only · stock has not changed."}
            </div>
          </>
        ) : (
          <div className="canvas-caption">
            <span className="pulse-square" />
            Describe a job or build a parts list. Review it before nesting.
          </div>
        )}
      </section>
      {shownResult && (
        <>
          {!complete && (
            <div className="notice warning">
              <FileText size={17} />
              <div>
                <strong>
                  {shownResult.nesting.total_requested -
                    shownResult.nesting.total_placed}{" "}
                  parts were not placed.
                </strong>
                <p>{shownResult.nesting.unplaced_instances.join(", ")}</p>
                <p>
                  Programs cover the placed subset only. A partial batch cannot
                  update inventory.
                </p>
              </div>
            </div>
          )}
          {details && (
            <section className="panel verification-panel">
              <h3>
                <ShieldCheck size={17} />
                Verification details
              </h3>
              <div className="check-row">
                <span>Placement geometry</span>
                <span>
                  {shownResult.nesting.sanitizer_verified ? (
                    <>
                      <Check size={13} />
                      Passed
                    </>
                  ) : (
                    "Failed"
                  )}
                </span>
              </div>
              {shownResult.gcode_programs.map((p) => (
                <div key={p.sheet_id} className="program-check">
                  <strong>{p.sheet_id}</strong>
                  <div className="check-row">
                    <span>Final G-code program</span>
                    <span>
                      {p.verification.verified_safe ? "Passed" : "Failed"}
                    </span>
                  </div>
                  <div className="check-row">
                    <span>Inside-out cut order</span>
                    <span>
                      {p.verification.inside_out_order_valid
                        ? "Passed"
                        : "Failed"}
                    </span>
                  </div>
                  <div className="check-row">
                    <span>Path across stock holes / outside sheet</span>
                    <span>
                      {p.verification.hole_collision_length_mm} /{" "}
                      {p.verification.outside_sheet_length_mm} mm
                    </span>
                  </div>
                </div>
              ))}
              <p>{shownResult.verification_scope}</p>
              <div className="timing-grid">
                {Object.entries(shownResult.timings_ms).map(([key, value]) => (
                  <div key={key}>
                    <span>{key.replace(/_ms$/, "").replaceAll("_", " ")}</span>
                    <strong>{formatNumber(value / 1000, 2)}s</strong>
                  </div>
                ))}
              </div>
              <button
                className="button secondary"
                onClick={() =>
                  downloadText(
                    JSON.stringify(shownResult, null, 2),
                    `${example ? "example-" : ""}cutting-plan.json`,
                    "application/json",
                  )
                }
              >
                Download result JSON <ArrowDownToLine size={13} />
              </button>
            </section>
          )}
          {!example && complete && (
            <section className="panel stock-update">
              <div>
                <span className="eyebrow">PREDICTED INVENTORY</span>
                <h3>
                  {committed
                    ? "Stock updated, all sheets together."
                    : "Ready to update your stock?"}
                </h3>
                <p>
                  {committed
                    ? "Reindex physical remnants after moving them. No cut has been performed by this application."
                    : "This action reruns planning, verifies the new result and updates predicted remaining stock atomically."}
                </p>
              </div>
              <button
                className="button secondary"
                disabled={committed || !!busy}
                onClick={() => onCommit()}
              >
                {committed ? (
                  <>
                    <CheckCircle2 size={14} />
                    Updated
                  </>
                ) : (
                  <>
                    Replan & update stock <ArrowUpRight size={14} />
                  </>
                )}
              </button>
            </section>
          )}
        </>
      )}
    </div>
  );
}
