"""Regression tests for failed exports, rollback, grades and uploaded jobs."""
import json
import sqlite3
from dataclasses import replace

import cv2
import ezdxf
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory, RemnantWarehouseDB
from backend.llm_client import LiveModelClient
from backend.materials import normalize_material
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import PlacedPartInstance
from backend.m4_muse_gcode import GCodeCompiler
from backend.sam_client import decode_image_output, segment_image


@pytest.mark.parametrize("label,canonical", [
    ("Stainless Steel 304", "ss304"), ("SS 316", "ss316"),
    ("SS304L", "ss304l"), ("A36", "a36"), ("Aluminium 6061", "al6061"),
    ("al5052", "al5052"), ("stainless steel", "stainless_steel"),
    ("mild steel", "mild_steel"), ("aluminum 6061-T6", "aluminum_6061_t6"),
])
def test_canonical_material_preserves_grades(label, canonical):
    assert normalize_material(label) == canonical


def test_material_grade_queries_do_not_substitute(tmp_path):
    db = RemnantWarehouseDB(str(tmp_path / "materials.db"))
    for material in ("ss304", "ss316", "a36", "steel", "stainless steel", "mild steel", "al6061", "al5052"):
        db.upsert_remnant(material, material, 3, box(0, 0, 100, 100))
    assert [r.sheet_id for r in db.query_compatible_remnants("Stainless Steel 304", 3)] == ["ss304"]
    assert [r.sheet_id for r in db.query_compatible_remnants("stainless", 3)] == ["stainless steel"]
    assert [r.sheet_id for r in db.query_compatible_remnants("al6061", 3)] == ["al6061"]
    assert [r.sheet_id for r in db.query_compatible_remnants("steel", 3)] == ["steel"]


def compiled_rectangle():
    compiler = GCodeCompiler()
    sheet = box(0, 0, 100, 100)
    part = PlacedPartInstance("P_1", "P", "rectangle", "S", 10, 10, 0, box(10, 10, 30, 30))
    return compiler, sheet, compiler.compile_iso_gcode("S", sheet, [part])


@pytest.mark.parametrize("bad_block", ["G91", "G20", "M08", "G02 X20 Y20 I1 J2", "G01 X1 Y1 G91", "M03 M08", "G92 X0 Y0", "G01 XNaN Y1", "G01 X1 X2 Y3", "G01 X1 Y2 F-100", "%"])
def test_unknown_and_unsafe_blocks_fail_closed(bad_block):
    compiler, sheet, cg = compiled_rectangle()
    program = cg.gcode_text.replace("M30", bad_block + "\nM30")
    report = compiler.verify_gcode_toolpath(program, sheet, cg.ordered_loops)
    assert not report.verified_safe
    assert report.error_message


def test_valid_but_wrong_contour_cannot_borrow_expected_loop_metadata():
    compiler, sheet, cg = compiled_rectangle()
    text = cg.gcode_text.replace("X30.000", "X31.000")
    assert not compiler.verify_gcode_toolpath(text, sheet, cg.ordered_loops).verified_safe
    assert not compiler.verify_gcode_toolpath(cg.gcode_text.replace("M30 ; End of program", ""), sheet, cg.ordered_loops).verified_safe


def test_only_supported_postprocessor_and_safe_comments():
    compiler, sheet, cg = compiled_rectangle()
    with pytest.raises(ValueError, match="UNSUPPORTED_POSTPROCESSOR"):
        compiler.apply_machine_profile("Fanuc or Trumpf", cg)
    assert compiler.safe_comment("S\nG91\rM08") == "S G91 M08"
    profile = compiler.apply_machine_profile("ISO_6983_GRBL", cg)
    assert compiler.verify_gcode_toolpath(profile, sheet, cg.ordered_loops).verified_safe


def make_api(tmp_path):
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    return app, TestClient(app)


def two_sheet_job(app):
    for sid in ("A", "B"):
        app.state.db.upsert_remnant(sid, "ss304", 3, box(0, 0, 60, 60))
    return {"order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1,
                      "parts": [{"part_id": "P", "shape_type": "rectangle", "width_mm": 40, "height_mm": 40, "quantity": 2}]},
            "coarse_step_mm": 5, "commit_cuts_to_db": True}


def test_complete_two_sheet_batch_commits_both_verified_programs(tmp_path):
    app, client = make_api(tmp_path)
    response = client.post("/api/v1/execute-pipeline", json=two_sheet_job(app))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["nesting"]["sheets_used"] == 2
    assert result["nesting"]["total_placed"] == 2
    assert {p["sheet_id"] for p in result["gcode_programs"]} == {"A", "B"}
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])
    assert all(app.state.db.get_remnant(s).usable_area_mm2 < 3600 for s in ("A", "B"))


def test_legacy_python_entry_points_still_generate_verified_output():
    from backend.m3_nfp_nester import HoleAwareNester, HoleAwareNFPNester
    from backend.m4_muse_gcode import MuseGCodeCompiler
    assert HoleAwareNFPNester is HoleAwareNester
    compiler, sheet, compiled = compiled_rectangle()
    legacy = MuseGCodeCompiler().synthesize_custom_postprocessor_via_muse_code("GRBL", compiled)
    assert legacy == compiler.apply_machine_profile("GRBL", compiled)
    assert compiler.verify_gcode_toolpath(legacy, sheet, compiled.ordered_loops).verified_safe


def test_second_sheet_failure_blocks_entire_batch_and_export(tmp_path, monkeypatch):
    app, client = make_api(tmp_path)
    request = two_sheet_job(app)
    original = GCodeCompiler.compile_iso_gcode
    calls = []

    def fail_second(self, *args, **kwargs):
        cg = original(self, *args, **kwargs)
        calls.append(cg.sheet_id)
        if len(calls) == 2:
            cg.verification = replace(cg.verification, verified_safe=False, error_message="injected failure")
        return cg

    monkeypatch.setattr(GCodeCompiler, "compile_iso_gcode", fail_second)
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert len(calls) == 2
    assert response.status_code == 422
    assert "gcode_programs" not in response.json()
    assert app.state.db.get_remnant("A").usable_area_mm2 == 3600
    assert app.state.db.get_remnant("B").usable_area_mm2 == 3600


def test_final_postprocessed_text_is_verified_before_commit(tmp_path, monkeypatch):
    app, client = make_api(tmp_path)
    request = two_sheet_job(app)
    original = GCodeCompiler.apply_machine_profile

    def inject(self, *args, **kwargs):
        return "G91\n" + original(self, *args, **kwargs)

    monkeypatch.setattr(GCodeCompiler, "apply_machine_profile", inject)
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert response.status_code == 422
    assert app.state.db.get_remnant("A").usable_area_mm2 == 3600


def test_sql_failure_rolls_back_first_sheet(tmp_path):
    db = RemnantWarehouseDB(str(tmp_path / "atomic.db"))
    for sid in ("A", "B"):
        db.upsert_remnant(sid, "steel", 3, box(0, 0, 100, 100))
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("CREATE TRIGGER fail_b BEFORE INSERT ON remnants WHEN NEW.sheet_id='B' BEGIN SELECT RAISE(ABORT, 'injected SQL failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        db.commit_cut_batch({"A": [box(10, 10, 20, 20)], "B": [box(10, 10, 20, 20)]})
    assert db.get_remnant("A").usable_area_mm2 == 10000
    assert db.get_remnant("B").usable_area_mm2 == 10000


def test_stale_plan_rejected_and_donut_slug_preserved(tmp_path):
    db = RemnantWarehouseDB(str(tmp_path / "islands.db"))
    before = db.upsert_remnant("A", "steel", 3, box(0, 0, 100, 100))
    ring = box(20, 20, 80, 80).difference(box(30, 30, 70, 70))
    updated = db.commit_cut_batch({"A": [ring]}, expected_wkts={"A": before.polygon.wkt})
    assert len(updated) == 2
    assert sum(r.usable_area_mm2 for r in updated) == 8000
    assert all(r.dxf_path == "" for r in updated)
    with pytest.raises(ValueError, match="STALE_WAREHOUSE"):
        db.commit_cut_batch({"A": [box(1, 1, 2, 2)]}, expected_wkts={"A": before.polygon.wkt})


def test_upload_then_make_fifty_verified_parts(tmp_path):
    app, client = make_api(tmp_path)
    app.state.db.upsert_remnant("STOCK_304", "ss304", 3, box(0, 0, 150, 100))
    app.state.db.upsert_remnant("WRONG_316", "ss316", 3, box(0, 0, 150, 100))
    vendor = tmp_path / "vendor.dxf"
    CADPartFactory.save_part_to_dxf(box(0, 0, 5, 4), str(vendor))
    upload = client.post("/api/v1/upload-dxf", files={"file": ("vendor.dxf", vendor.read_bytes(), "application/dxf")})
    assert upload.status_code == 200
    uploaded = upload.json()["dxf_path"]
    parsed = client.post("/api/v1/parse-order", json={"prompt": "Cut 50 of the uploaded dxf file from 3mm ss304 sheet, kerf 1mm", "uploaded_dxf_files": [uploaded]})
    assert parsed.status_code == 200, parsed.text
    order = parsed.json()["order"]
    assert order["parts"][0]["quantity"] == 50
    assert order["parts"][0]["dxf_path"] == uploaded
    response = client.post("/api/v1/execute-pipeline", json={"order": order, "coarse_step_mm": 5, "commit_cuts_to_db": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["nesting"]["total_placed"] == 50
    assert all(p["verification"]["verified_safe"] for p in data["gcode_programs"])
    assert all(r["sheet_id"] == "STOCK_304" for r in data["candidate_sheets"])
    assert app.state.db.get_remnant("WRONG_316").usable_area_mm2 == 15000
    assert data["metrics"]["money_saved"] is None
    assert data["timings_ms"]["total_ms"] > 0


@pytest.mark.parametrize("kind", ["circle", "open", "bulge", "outside", "inches"])
def test_unsupported_dxf_rejected(tmp_path, kind):
    doc = ezdxf.new("R2010")
    doc.units = 1 if kind == "inches" else 4
    msp = doc.modelspace()
    if kind == "circle":
        msp.add_circle((10, 10), 5)
    else:
        msp.add_lwpolyline([(0, 0), (40, 0), (40, 40), (0, 40)], close=kind != "open")
        if kind == "bulge":
            msp.add_lwpolyline([(10, 10, 1), (20, 10, 0), (20, 20, 0)], format="xyb", close=True)
        if kind == "outside":
            msp.add_lwpolyline([(60, 0), (70, 0), (70, 10), (60, 10)], close=True)
    path = tmp_path / (kind + ".dxf")
    doc.saveas(path)
    with pytest.raises(ValueError, match="ERR_DXF"):
        CADPartFactory.load_part_from_dxf(str(path))


def test_demo_stock_requires_explicit_opt_in_and_external_paths_rejected(tmp_path):
    _, client = make_api(tmp_path)
    assert client.post("/api/v1/seed-demo-warehouse").json()["inventory_source"] == "demo"
    order = {"material": "steel", "thickness_mm": 3, "parts": [{"shape_type": "circle", "diameter_mm": 10}]}
    assert client.post("/api/v1/execute-pipeline", json={"order": order}).status_code == 422
    order["parts"] = [{"shape_type": "dxf_file", "dxf_path": str(tmp_path / "outside.dxf")}]
    assert client.post("/api/v1/execute-pipeline", json={"order": order}).status_code == 422


# Official Meta example: a lossless 27x60 mask at source box (211,228)..(270,254).
# This is a wire-contract fixture, not a claim of measured sheet accuracy.
SAM_EXAMPLE = "<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x(|>"


def test_official_sam_mask_is_decoded_and_placed_at_source_box():
    mask, object_id = decode_image_output(SAM_EXAMPLE, (334, 320, 3))
    assert object_id == "0"
    assert mask.shape == (334, 320)
    assert mask[228:255, 211:271].any()
    assert not mask[:228].any()
    assert not mask[:, :211].any()
    with pytest.raises(ValueError, match="IMAGE_SIZE"):
        decode_image_output(SAM_EXAMPLE, (100, 100, 3))
    with pytest.raises(ValueError, match="OBJECT_SELECTION"):
        decode_image_output(SAM_EXAMPLE + SAM_EXAMPLE.replace("<0f>0", ",1"), (334, 320, 3))


def test_sam_uses_responses_sse_and_never_chat_completion(monkeypatch):
    client_class = httpx.Client
    calls = []
    def transport(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["model"] == "sam-3.1"
        assert payload["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")
        events = [{"type": "response.output_text.delta", "delta": SAM_EXAMPLE}, {"type": "response.completed"}]
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="".join("data: " + json.dumps(e) + "\n\n" for e in events))
    monkeypatch.setattr("backend.sam_client.httpx.Client", lambda **kwargs: client_class(transport=httpx.MockTransport(transport), **kwargs))
    llm = LiveModelClient()
    llm.meta_api_key = "fake-unit-test-key"
    mask, trace = segment_image(llm, np.zeros((334, 320, 3), dtype=np.uint8), "sheet")
    assert len(calls) == 1 and mask.any()
    assert trace["source"] == "meta_sam_3.1"


def test_no_sam_key_does_not_silently_threshold_and_small_holes_survive():
    indexer = RemnantOpticalIndexer(StationCalibrationConfig())
    image = np.zeros((900, 1200, 3), dtype=np.uint8)
    image[100:700, 200:1000] = 240
    image[300:304, 400:404] = 0
    with pytest.raises(ValueError, match="SAM_NOT_CONFIGURED"):
        indexer.fetch_sam3_mask(image)
    mask = indexer.fetch_sam3_mask(image, segmentation_mode="local_threshold", use_clahe=True)
    poly = indexer.build_topological_polygon(mask)
    assert len(poly.interiors) == 1
    assert indexer.last_vision_audit["segmentation"]["source"] == "local_threshold"
    assert not indexer.last_vision_audit["segmentation"]["physical_accuracy_validated"]


@pytest.mark.parametrize("prompt", [
    "Cut 2 circles of 20mm plus 3 triangles of 40mm from 3mm steel sheet",
    "Cut 2 rings with 120mm outer diameter plus 1 circle of 30mm from 3mm steel sheet",
    "Cut 2 circles of 20mm from steel sheet",
    "Cut 2 circles of 20mm from 3mm sheet",
    "Cut 2 circles of -20mm from 3mm steel sheet",
])
def test_local_parser_rejects_omitted_parts_and_guessed_requirements(prompt):
    with pytest.raises(ValueError):
        SparkWarehouseOrchestrator.fallback_regex_parse_prompt(prompt)


def test_local_parser_ring_comma_and_explicit_kerf():
    order = SparkWarehouseOrchestrator.fallback_regex_parse_prompt(
        "Cut 2 stainless steel washers with 120mm OD, 60mm ID from 3mm stainless steel sheet, kerf 1.2mm")
    assert order["parts"][0]["inner_diam_mm"] == 60
    assert order["material"] == "stainless_steel"
    assert order["kerf_mm"] == 1.2


def test_cloud_parser_cannot_downgrade_explicit_grade():
    class DowngradingModel:
        def chat_completion(self, **kwargs):
            return {"ok": True, "provider": "fake", "model": "fake", "latency_ms": 1,
                    "reasoning_content": "", "content": "", "usage": {},
                    "parsed_json": {"material": "steel", "thickness_mm": 3, "parts": [
                        {"shape_type": "circle", "diameter_mm": 20, "quantity": 2}]}}
    orch = SparkWarehouseOrchestrator(RemnantWarehouseDB(":memory:"), DowngradingModel())
    with pytest.raises(ValueError, match="CHANGED_MATERIAL_GRADE"):
        orch.parse_natural_language_order_via_spark("Cut 2 circles 20mm from 3mm ss316 sheet")


def test_material_change_during_planning_blocks_commit(tmp_path):
    db = RemnantWarehouseDB(str(tmp_path / "stale-material.db"))
    before = db.upsert_remnant("A", "ss304", 3, box(0, 0, 100, 100))
    db.upsert_remnant("A", "ss316", 3, before.polygon)
    with pytest.raises(ValueError, match="STALE_WAREHOUSE_MATERIAL"):
        db.commit_cut_batch({"A": [box(10, 10, 20, 20)]}, expected_wkts={"A": before.polygon.wkt},
                            expected_inventory={"A": (before.material, before.thickness_mm, before.source)})
    assert db.get_remnant("A").usable_area_mm2 == 10000


def test_partial_batch_never_commits(tmp_path):
    app, client = make_api(tmp_path)
    request = two_sheet_job(app)
    request["order"]["parts"][0]["quantity"] = 3
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert response.status_code == 422 and "PARTIAL_BATCH" in response.text
    assert all(app.state.db.get_remnant(s).usable_area_mm2 == 3600 for s in ("A", "B"))


def test_synthetic_photo_to_saved_geometry_keeps_local_provenance(tmp_path):
    from backend.tests.test_module1_calibration import _create_synthetic_station_image
    import base64
    app, client = make_api(tmp_path)
    photo = _create_synthetic_station_image()
    _, encoded = cv2.imencode(".png", photo)
    request = {"sheet_id": "LOCAL_TEST", "material": "ss304", "image_base64": base64.b64encode(encoded).decode(),
               "segmentation_mode": "local_threshold"}
    response = client.post("/api/v1/index-remnant", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["camera_angle_deg"] is None
    assert result["saved_remnant"]["inventory_source"] == "local_threshold"
    bounds = result["geometry"]["bounds"]
    assert abs((bounds[2] - bounds[0]) - 300) < 2
    assert abs((bounds[3] - bounds[1]) - 200) < 2
    assert result["timings_ms"]["total_ms"] > 0
    assert app.state.db.get_remnant("LOCAL_TEST").source == "local_threshold"
    pipeline = {"order": {"material": "ss304", "thickness_mm": 3,
                          "parts": [{"shape_type": "circle", "diameter_mm": 20}]}}
    assert client.post("/api/v1/execute-pipeline", json=pipeline).status_code == 422


def test_sam_no_match_and_truncated_stream_fail_closed(monkeypatch):
    with pytest.raises(ValueError, match="NO_MATCH"):
        decode_image_output("", (334, 320, 3))
    client_class = httpx.Client
    event = {"type": "response.output_text.delta", "delta": SAM_EXAMPLE}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, text="data: " + json.dumps(event) + "\n\n"))
    monkeypatch.setattr("backend.sam_client.httpx.Client", lambda **kwargs: client_class(transport=transport, **kwargs))
    llm = LiveModelClient()
    llm.meta_api_key = "fake-unit-test-key"
    with pytest.raises(ValueError, match="INCOMPLETE_STREAM"):
        segment_image(llm, np.zeros((334, 320, 3), np.uint8), box_prompt=[211, 228, 271, 255])
