import cv2
import numpy as np
import pytest
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, RemnantWarehouseDB
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import HoleAwareNester
from backend.m4_muse_gcode import GCodeCompiler


def _render_tilted_station_photo_and_mask(
    cfg: StationCalibrationConfig,
    sheet_bbox_mm: tuple[float, float, float, float],
    hole_bboxes_mm: list[tuple[float, float, float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Simulates a physical 600x450mm ArUco Indexing Table photographed at an oblique tilt,

    along with the segmentation mask of a sheet and its interior cutout holes.
    """
    scale = cfg.px_per_mm
    W_px = int(cfg.table_width_mm * scale)
    H_px = int(cfg.table_height_mm * scale)
    S_px = int(cfg.marker_size_mm * scale)
    pad_px = int(25.0 * scale)
    quiet_px = int(8.0 * scale)

    canvas = np.zeros((H_px + 2 * pad_px, W_px + 2 * pad_px, 3), dtype=np.uint8)
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    corners_tl = {
        0: (pad_px, pad_px),
        1: (pad_px + W_px - S_px, pad_px),
        2: (pad_px + W_px - S_px, H_px - S_px),
        3: (pad_px, pad_px + H_px - S_px),
    }

    for mid, (x0, y0) in corners_tl.items():
        canvas[
            y0 - quiet_px : y0 + S_px + quiet_px,
            x0 - quiet_px : x0 + S_px + quiet_px,
        ] = 255
        marker_img = cv2.aruco.generateImageMarker(aruco_dict, mid, S_px)
        canvas[y0 : y0 + S_px, x0 : x0 + S_px] = cv2.cvtColor(
            marker_img, cv2.COLOR_GRAY2BGR
        )

    # Draw sheet on both the camera canvas and the ground-truth orthographic mask
    ortho_mask = np.zeros((H_px, W_px), dtype=np.uint8)
    sx0, sy0, sx1, sy1 = [int(v * scale) for v in sheet_bbox_mm]
    ortho_mask[sy0:sy1, sx0:sx1] = 255
    canvas[pad_px + sy0 : pad_px + sy1, pad_px + sx0 : pad_px + sx1] = (200, 200, 200)

    for hx0, hy0, hx1, hy1 in hole_bboxes_mm:
        ix0, iy0, ix1, iy1 = [int(v * scale) for v in (hx0, hy0, hx1, hy1)]
        ortho_mask[iy0:iy1, ix0:ix1] = 0
        canvas[pad_px + iy0 : pad_px + iy1, pad_px + ix0 : pad_px + ix1] = (15, 15, 15)

    # Apply oblique perspective tilt to the camera canvas
    ch, cw = canvas.shape[:2]
    src = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], dtype=np.float32)
    dst = np.array(
        [
            [cw * 0.06, ch * 0.10],
            [cw * 0.94, ch * 0.08],
            [cw * 0.98, ch * 0.96],
            [cw * 0.02, ch * 0.94],
        ],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(src, dst)
    tilted_bgr = cv2.warpPerspective(canvas, M, (cw, ch), borderValue=(10, 10, 10))
    return tilted_bgr, ortho_mask


def test_phase_b_complete_factory_lifecycle(tmp_path):
    """Master End-to-End Phase B Integration Test:

    [B2 Camera Calibration & Vectorization] -> [B1 SQLite Warehouse Storage]
    -> [B4 Order Orchestration & DXF Loading] -> [B3 Multi-Sheet Hole-Aware Nesting]
    -> [B5 Inside-Out G-Code Compilation & Verification]
    -> [B1 Commit Cut State Mutation] -> [Second Job Avoiding First Job's Cuts!]
    """
    db_path = str(tmp_path / "factory_lifecycle.db")
    db = RemnantWarehouseDB(db_path=db_path)
    cfg = StationCalibrationConfig(
        table_width_mm=600.0, table_height_mm=450.0, marker_size_mm=50.0, px_per_mm=2.0
    )
    indexer = RemnantOpticalIndexer(cfg)

    # =========================================================================
    # STEP 1 (B2 -> B1): Optically Index 2 Tilted Camera Photos into SQLite
    # =========================================================================
    # Sheet A (Smaller Remnant): 220x180mm sheet (X: 150..370, Y: 120..300) with a 50x50mm center hole
    photo_a, mask_a = _render_tilted_station_photo_and_mask(
        cfg,
        sheet_bbox_mm=(150.0, 120.0, 370.0, 300.0),
        hole_bboxes_mm=[(235.0, 185.0, 285.0, 235.0)],
    )
    cal_a = indexer.calibrate_and_flatten(photo_a)
    assert cal_a.scale_drift_mm < 0.5
    poly_a = indexer.build_topological_polygon(mask_a, epsilon_mm=0.5)
    dxf_a = str(tmp_path / "sheet_a.dxf")
    indexer.export_remnant_dxf(poly_a, dxf_a)
    rec_a = db.upsert_remnant("REMNANT_SMALL_A", "steel", 3.0, poly_a, dxf_a)

    # Sheet B (Larger L-Hole Remnant): 360x260mm sheet (X: 120..480, Y: 95..355) with an L-shaped hole
    photo_b, mask_b = _render_tilted_station_photo_and_mask(
        cfg,
        sheet_bbox_mm=(120.0, 95.0, 480.0, 355.0),
        hole_bboxes_mm=[
            (250.0, 160.0, 330.0, 280.0),  # Vertical leg of L-hole
            (330.0, 220.0, 390.0, 280.0),  # Horizontal leg of L-hole
        ],
    )
    cal_b = indexer.calibrate_and_flatten(photo_b)
    assert cal_b.scale_drift_mm < 0.5
    poly_b = indexer.build_topological_polygon(mask_b, epsilon_mm=0.5)
    dxf_b = str(tmp_path / "sheet_b.dxf")
    indexer.export_remnant_dxf(poly_b, dxf_b)
    rec_b = db.upsert_remnant("REMNANT_LARGE_B", "steel", 3.0, poly_b, dxf_b)

    assert rec_a.hole_count == 1
    assert rec_b.hole_count == 1
    assert rec_a.usable_area_mm2 < rec_b.usable_area_mm2

    # =========================================================================
    # STEP 2 (B4 -> B1): Create Custom .DXF Part & Orchestrate Multi-Part Order #1
    # =========================================================================
    custom_dxf_path = str(tmp_path / "custom_gusset.dxf")
    gusset_poly, _ = CADPartFactory.make_l_bracket(60.0, 60.0, 18.0)
    CADPartFactory.save_part_to_dxf(gusset_poly, custom_dxf_path)

    orchestrator = SparkWarehouseOrchestrator(db)
    order_1 = orchestrator.validate_and_parse_order_dict(
        {
            "order_id": "JOB_001",
            "material": "steel",
            "thickness_mm": 3.0,
            "kerf_mm": 3.0,
            "parts": [
                {"part_id": "HOLLOW_RING", "shape_type": "ring", "outer_diam_mm": 110.0, "inner_diam_mm": 72.0, "quantity": 1},
                {"part_id": "SMALL_DISK", "shape_type": "circle", "diameter_mm": 36.0, "quantity": 4},
                {"part_id": "RECT_PLATE", "shape_type": "rectangle", "width_mm": 75.0, "height_mm": 45.0, "quantity": 4},
                {"part_id": "DXF_GUSSET", "shape_type": "dxf_file", "dxf_path": custom_dxf_path, "quantity": 2},
            ],
        }
    )
    plan_1 = orchestrator.orchestrate_order_plan(order_1)

    # Verify Smallest-First Warehouse Ordering: REMNANT_SMALL_A must be first!
    assert [s.sheet_id for s in plan_1.candidate_sheets] == [
        "REMNANT_SMALL_A",
        "REMNANT_LARGE_B",
    ]
    assert plan_1.total_parts_count == 11

    # =========================================================================
    # STEP 3 (B3): Run Multi-Sheet Hole-Aware Nesting Across Both Sheets
    # =========================================================================
    nester = HoleAwareNester(kerf_mm=plan_1.kerf_mm, coarse_step_mm=6.0, fine_step_mm=1.0)
    nest_1 = nester.nest_batch_across_sheets(plan_1.candidate_sheets, plan_1.cad_part_specs)

    assert nest_1.status == "COMPLETE"
    assert nest_1.total_placed == 11
    assert nest_1.sheets_used == 2
    assert nest_1.sanitizer_verified is True

    # =========================================================================
    # STEP 4 (B5): Compile & Verify Inside-Out G-Code for Every Used Sheet
    # =========================================================================
    compiler = GCodeCompiler()
    for sheet_outcome in nest_1.sheet_outcomes:
        sheet_rec = db.get_remnant(sheet_outcome.sheet_id)
        compiled_gcode = compiler.compile_iso_gcode(
            sheet_id=sheet_outcome.sheet_id,
            raw_sheet_poly=sheet_rec.polygon,
            placed_parts=sheet_outcome.placed_parts,
            shift_to_sheet_corner=True,
        )
        assert compiled_gcode.verification.verified_safe is True
        assert compiled_gcode.verification.hole_collision_length_mm == 0.0
        assert compiled_gcode.verification.outside_sheet_length_mm == 0.0
        assert compiled_gcode.verification.inside_out_order_valid is True

    # =========================================================================
    # STEP 5 (B1 Lifecycle): Commit Job #1 Cuts to SQLite & Run Job #2!
    # =========================================================================
    outcome_a = next(o for o in nest_1.sheet_outcomes if o.sheet_id == "REMNANT_SMALL_A")
    cut_polys_job1 = [p.polygon for p in outcome_a.placed_parts]

    updated_a = db.commit_cut_to_sheet(
        "REMNANT_SMALL_A", cut_polys_job1, kerf_mm=plan_1.kerf_mm
    )
    # Usable area of REMNANT_SMALL_A must have decreased after committing Job #1
    assert updated_a.usable_area_mm2 < rec_a.usable_area_mm2

    # Job #2 reuses updated stock, spilling to another compatible sheet if the
    # first job's valid layout leaves insufficient space on that particular sheet.
    order_2 = orchestrator.validate_and_parse_order_dict(
        {
            "order_id": "JOB_002_FOLLOWUP",
            "material": "steel",
            "thickness_mm": 3.0,
            "kerf_mm": 3.0,
            "parts": [
                {"part_id": "TINY_PIN", "shape_type": "circle", "diameter_mm": 28.0, "quantity": 2}
            ],
        }
    )
    plan_2 = orchestrator.orchestrate_order_plan(order_2)
    nest_2 = nester.nest_batch_across_sheets(plan_2.candidate_sheets, plan_2.cad_part_specs)

    assert nest_2.status == "COMPLETE"
    assert any(o.sheet_id == "REMNANT_SMALL_A" for o in nest_2.sheet_outcomes)
    assert nest_2.total_placed == 2

    # Prove that Job #2's parts have 0.00 mm2 overlap with ALL of Job #1's committed parts!
    reused = next(o for o in nest_2.sheet_outcomes if o.sheet_id == "REMNANT_SMALL_A")
    for p2 in reused.placed_parts:
        for old_cut_poly in cut_polys_job1:
            assert p2.polygon.intersection(old_cut_poly).area == 0.0
