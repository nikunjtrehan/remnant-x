"""Order execution: parse, select stock, nest, verify every program, then commit once.

This module contains manufacturing orchestration; HTTP transport stays in api.py.
"""
import time
from pathlib import Path
from typing import Any, Dict, List
from shapely import affinity
from backend.llm_client import LiveModelClient
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import HoleAwareNester
from backend.m4_muse_gcode import GCodeCompiler
from backend.schemas import FullPipelineRequest
from backend.serialization import serialize_compiled_gcode, serialize_remnant, serialize_sheet_outcome


def checked_uploads(paths, upload_root: Path):
    result = []
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_relative_to(upload_root) or path.suffix.lower() != ".dxf" or not path.is_file():
            raise ValueError("ERR_UNMANAGED_DXF: use /api/v1/upload-dxf first")
        result.append(str(path))
    return result


def check_order_uploads(spec, upload_root: Path):
    checked_uploads([p.dxf_path for p in spec.parts if p.shape_type == "dxf_file"], upload_root)


def execute_pipeline(req: FullPipelineRequest, db, llm: LiveModelClient, upload_root: Path) -> Dict[str, Any]:
    orch = SparkWarehouseOrchestrator(db, llm_client=llm)
    started = time.perf_counter()
    timings = {}
    uploaded = checked_uploads(req.uploaded_dxf_files, upload_root)
    if req.prompt and req.order:
        raise ValueError("ERR_AMBIGUOUS_INPUT: provide prompt or order, not both")
    if req.prompt and req.prompt.strip():
        order_spec = orch.parse_natural_language_order_via_spark(req.prompt, uploaded)
    elif req.order:
        order_spec = orch.validate_and_parse_order_dict(req.order, uploaded)
    else:
        raise ValueError(
            "ERR_MISSING_INPUT: Provide either 'prompt' or structured 'order'."
        )

    check_order_uploads(order_spec, upload_root)
    timings["parse_ms"] = round((time.perf_counter() - started) * 1000, 2)
    stage = time.perf_counter()
    plan = orch.orchestrate_order_plan(order_spec)
    if not req.allow_demo_stock:
        plan.candidate_sheets = [r for r in plan.candidate_sheets if r.source not in {"demo", "local_threshold"} and not r.sheet_id.startswith("DEMO_")]
    timings["warehouse_query_ms"] = round((time.perf_counter() - stage) * 1000, 2)
    stage = time.perf_counter()
    if not plan.candidate_sheets:
        raise ValueError(
            f"ERR_NO_COMPATIBLE_REMNANTS: No {order_spec.material} ({order_spec.thickness_mm}mm) remnants found in warehouse."
        )

    nester = HoleAwareNester(
        kerf_mm=order_spec.kerf_mm,
        coarse_step_mm=req.coarse_step_mm,
        fine_step_mm=req.fine_step_mm,
    )
    batch_result = nester.nest_batch_across_sheets(
        sheets=plan.candidate_sheets,
        part_specs=plan.cad_part_specs,
    )

    timings["nesting_ms"] = round((time.perf_counter() - stage) * 1000, 2)
    stage = time.perf_counter()
    if not batch_result.sanitizer_verified:
        raise ValueError("ERR_UNVERIFIED_NESTING")
    compiler = GCodeCompiler(llm_client=llm)
    sheet_map = {s.sheet_id: s for s in plan.candidate_sheets}
    compiled_gcodes: List[Dict[str, Any]] = []
    updated_remnants: List[Dict[str, Any]] = []
    pending_cuts = {}
    expected_wkts = {}

    for outcome in batch_result.sheet_outcomes:
        if not outcome.placed_parts:
            continue
        raw_sheet = sheet_map[outcome.sheet_id]
        cg = compiler.compile_iso_gcode(
            sheet_id=outcome.sheet_id,
            raw_sheet_poly=raw_sheet.polygon,
            placed_parts=outcome.placed_parts,
        )
        cg.gcode_text = compiler.apply_machine_profile(
            req.machine_dialect_prompt or req.machine_profile, compiled_gcode=cg)
        cg.llm_trace = compiler.last_llm_trace
        # Re-parse the exact final program, including every added block.
        shifted = affinity.translate(raw_sheet.polygon, xoff=-cg.origin_x_mm, yoff=-cg.origin_y_mm)
        cg.verification = compiler.verify_gcode_toolpath(cg.gcode_text, shifted, cg.ordered_loops)
        if not cg.verification.verified_safe:
            raise ValueError("ERR_UNSAFE_GCODE: " + cg.verification.error_message)
        compiled_gcodes.append(serialize_compiled_gcode(cg))
        pending_cuts[outcome.sheet_id] = [p.polygon for p in outcome.placed_parts]
        expected_wkts[outcome.sheet_id] = raw_sheet.polygon.wkt

    timings["compile_and_verify_ms"] = round((time.perf_counter() - stage) * 1000, 2)
    # Serialize before committing: a response construction failure cannot
    # quietly consume stock. The actual commit occurs only after this.
    outcomes_json = [serialize_sheet_outcome(o) for o in batch_result.sheet_outcomes]
    candidates_json = [serialize_remnant(s) for s in plan.candidate_sheets]
    stage = time.perf_counter()
    if req.commit_cuts_to_db:
        if batch_result.total_placed != batch_result.total_requested:
            raise ValueError("ERR_PARTIAL_BATCH: all requested parts must fit before commit")
        updated_remnants = [serialize_remnant(r) for r in db.commit_cut_batch(
            pending_cuts, order_spec.kerf_mm, expected_wkts,
            {sid: (sheet_map[sid].material, sheet_map[sid].thickness_mm, sheet_map[sid].source) for sid in pending_cuts})]
    timings["commit_ms"] = round((time.perf_counter() - stage) * 1000, 2)
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
    used = [o for o in batch_result.sheet_outcomes if o.placed_parts]
    input_area = sum(o.initial_usable_area_mm2 for o in used)
    part_area = sum(p.polygon.area for o in used for p in o.placed_parts)

    return {
        "status": batch_result.status,
        "machine_profile": req.machine_profile,
        "timings_ms": timings,
        "metrics": {"sheets_used": len(used), "input_usable_area_mm2": round(input_area, 2),
                    "placed_solid_area_mm2": round(part_area, 2),
                    "usable_area_utilization_pct": round(100 * part_area / input_area, 2) if input_area else 0,
                    "money_saved": None, "co2_saved_kg": None,
                    "savings_note": "Requires a measured virgin-stock baseline, prices and lifecycle assumptions."},
        "verification_scope": "Planned centerline geometry and supported GRBL commands; excludes physical sheet accuracy, kerf compensation and machine process qualification.",
        "order": {
            "order_id": order_spec.order_id,
            "material": order_spec.material,
            "thickness_mm": order_spec.thickness_mm,
            "kerf_mm": order_spec.kerf_mm,
            "total_parts_count": plan.total_parts_count,
            "total_solid_area_mm2": plan.total_solid_area_mm2,
        },
        "orchestration_llm_trace": plan.llm_trace,
        "candidate_sheets": candidates_json,
        "nesting": {
            "status": batch_result.status,
            "total_requested": batch_result.total_requested,
            "total_placed": batch_result.total_placed,
            "sheets_used": batch_result.sheets_used,
            "sanitizer_verified": batch_result.sanitizer_verified,
            "unplaced_instances": batch_result.unplaced_instances,
            "sheet_outcomes": outcomes_json,
        },
        "gcode_programs": compiled_gcodes,
        "committed_remnants": updated_remnants,
    }
