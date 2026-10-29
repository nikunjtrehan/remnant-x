from fastapi.testclient import TestClient
import pytest
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from backend.api import create_app
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import PlacedPartInstance
from backend.m4_muse_gcode import GCodeCompiler
from backend.postprocessor import render_emitter


def arc_job():
    stock = box(0, 0, 100, 100)
    poly = Polygon(box(20, 20, 60, 60).exterior.coords, [box(30, 30, 40, 40).exterior.coords])
    compiler = GCodeCompiler(lead_in_radius_mm=1, cut_feedrate_mm_min=900,
                              pierce_delay_sec=0.2, laser_power_s=400)
    placed = [PlacedPartInstance("P", "P", "plate", "S", 20, 20, 0, poly)]
    return compiler, stock, compiler.compile_iso_gcode("S", stock, placed)


@pytest.mark.parametrize("profile,end", [("ISO_6983_GRBL", "M30"), ("LINUXCNC_LASER", "M02")])
def test_real_prepared_emitters_preserve_arc_leads_and_process(profile, end):
    compiler, stock, compiled = arc_job()
    assert "G02 " in compiled.gcode_text and "G03 " in compiled.gcode_text
    assert [s.loop_type for s in compiled.ordered_loops] == ["INTERNAL_HOLE", "OUTER_PERIMETER"]
    emitted = compiler.apply_machine_profile(profile, compiled)
    report = compiler.verify_gcode_toolpath(emitted, stock, compiled.ordered_loops, machine_profile=profile)
    assert report.verified_safe, report.error_message
    assert emitted.strip().endswith(end)
    assert compiler.last_llm_trace["provider"] == "muse-code-prepared"
    assert compiler.last_llm_trace["generation_is_live_per_job"] is False
    assert report.total_cut_distance_mm == pytest.approx(200 + 3.14159, abs=0.01)
    if profile == "LINUXCNC_LASER":
        assert not compiler.verify_gcode_toolpath(emitted.replace("G61", "; removed G61"), stock,
                                                 compiled.ordered_loops, machine_profile=profile).verified_safe


@pytest.mark.parametrize("before,after", [
    ("G17 ; XY arc plane", ""),
    ("G91.1 ; Incremental I/J arc centres", ""),
    ("G02 ", "G03 "),
    ("F900.0", "F901.0"),
    ("S400", "S999"),
    ("G04 P0.20", "G04 P0.30"),
    ("G04 P0.20 ; Pierce dwell", ""),
    ("M05 ; Ensure laser beam OFF before homing", ""),
    ("G90 ; Absolute positioning", "G90.000000001"),
])
def test_arc_or_process_tampering_cannot_borrow_safe_plan(before, after):
    compiler, stock, compiled = arc_job()
    assert before in compiled.gcode_text
    assert not compiler.verify_gcode_toolpath(compiled.gcode_text.replace(before, after), stock, compiled.ordered_loops).verified_safe


def test_requested_lead_fails_when_there_is_no_waste_for_piercing():
    stock = box(0, 0, 10, 10)
    with pytest.raises(ValueError, match="ERR_NO_SAFE_LEAD_IN"):
        GCodeCompiler(lead_in_radius_mm=1).compile_iso_gcode(
            "S", stock, [PlacedPartInstance("P", "P", "plate", "S", 0, 0, 0, stock)])


@pytest.mark.parametrize("hollow", [False, True])
def test_arc_leads_fit_dense_circle_chords_and_ring_holes(hollow):
    poly = Point(50, 50).buffer(20, quad_segs=32)
    if hollow:
        poly = poly.difference(Point(50, 50).buffer(10, quad_segs=32))
    assert max(LineString([a, b]).length for a, b in zip(poly.exterior.coords, list(poly.exterior.coords)[1:])) < 4
    stock = box(0, 0, 100, 100)
    compiler = GCodeCompiler(lead_in_radius_mm=2)
    compiled = compiler.compile_iso_gcode("S", stock, [PlacedPartInstance("P", "P", "round", "S", 30, 30, 0, poly)])
    assert len(compiled.ordered_loops) == (2 if hollow else 1)
    assert all(loop.lead_in for loop in compiled.ordered_loops)
    emitted = compiler.apply_machine_profile("LINUXCNC_LASER", compiled)
    report = compiler.verify_gcode_toolpath(emitted, stock, compiled.ordered_loops, machine_profile="LINUXCNC_LASER")
    assert report.verified_safe, report.error_message


@pytest.mark.parametrize("statement", [
    "import os", "__import__('os')", "lines = job['blocks']",
    "lines.append(block.__class__)", "lines.append(f'{1:{block}}')",
    "emit(job)", "job['blocks'] = []",
])
def test_emitter_contract_rejects_general_python(statement):
    source = "def emit(job):\n    lines = []\n    for block in job['blocks']:\n        " + statement + "\n    return '\\n'.join(lines)\n"
    with pytest.raises((ValueError, SyntaxError), match="ERR_POSTPROCESSOR|invalid syntax"):
        render_emitter(source, {"blocks": [{"op": "M30"}]})


def test_failed_final_emitter_blocks_both_sheet_commits(tmp_path, monkeypatch):
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    for sid in ("A", "B"):
        app.state.db.upsert_remnant(sid, "ss304", 3, box(0, 0, 60, 60))
    original = GCodeCompiler.apply_machine_profile
    calls = []

    def corrupt_second(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        calls.append(result)
        return result.replace("F1800.0", "F2000.0") if len(calls) == 2 else result

    monkeypatch.setattr(GCodeCompiler, "apply_machine_profile", corrupt_second)
    response = TestClient(app).post("/api/v1/execute-pipeline", json={
        "order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 2,
                  "parts": [{"part_id": "P", "shape_type": "rectangle", "width_mm": 40, "height_mm": 40, "quantity": 2}]},
        "lead_in_radius_mm": 1, "machine_profile": "LINUXCNC_LASER", "commit_cuts_to_db": True})
    assert response.status_code == 422, response.text
    assert len(calls) == 2
    assert all(app.state.db.get_remnant(s).usable_area_mm2 == 3600 for s in ("A", "B"))


@pytest.mark.parametrize("offset", [(0, 0), (120, 85)])
def test_committed_inventory_subtracts_lead_in_and_kerf_as_well_as_part(tmp_path, offset):
    app = create_app(str(tmp_path / "inventory.db"), str(tmp_path / "artifacts"))
    stock = affinity.translate(box(0, 0, 100, 100), *offset)
    app.state.db.upsert_remnant("S", "ss304", 3, stock)
    response = TestClient(app).post("/api/v1/execute-pipeline", json={
        "order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 2,
                  "parts": [{"part_id": "P", "shape_type": "rectangle", "width_mm": 20, "height_mm": 20}]},
        "lead_in_radius_mm": 1, "commit_cuts_to_db": True})
    assert response.status_code == 200, response.text
    result = response.json()
    geometry = result["nesting"]["sheet_outcomes"][0]["placed_parts"][0]["geometry"]
    solid = Polygon(geometry["exterior"], geometry["holes"])
    arc = result["gcode_programs"][0]["ordered_loops"][0]["lead_in"]
    lead = affinity.translate(LineString(arc["points"]), *offset).buffer(arc["sampling_error_bound_mm"])
    expected = stock.difference(unary_union([solid.buffer(1), lead.buffer(1)]))
    actual = app.state.db.get_remnant("S").polygon
    assert actual.symmetric_difference(expected).area < 1e-7
    assert actual.area < stock.difference(solid.buffer(1)).area
    assert result["nesting"]["sheet_outcomes"][0]["remaining_usable_area_mm2"] == round(actual.area, 2)


def test_photo_indexing_requires_supplied_material_and_thickness(tmp_path):
    app = create_app(str(tmp_path / "untouched.db"), str(tmp_path / "artifacts"))
    response = TestClient(app).post("/api/v1/index-remnant", json={"image_base64": "invalid"})
    assert response.status_code == 422
    assert {item["loc"][-1] for item in response.json()["detail"]} >= {"material", "thickness_mm"}
    assert not (tmp_path / "untouched.db").exists()


class RepairModel:
    has_fireworks = True

    def __init__(self, corrected=True):
        self.corrected = corrected
        self.calls = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        qty = 5 if len(self.calls) == 2 and self.corrected else 6
        return {"ok": True, "provider": kwargs["prefer_provider"], "model": "test-model",
                "latency_ms": 0, "reasoning_content": "", "content": "", "usage": {},
                "parsed_json": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1,
                                "parts": [{"part_id": "P", "shape_type": "circle", "quantity": qty, "diameter_mm": 20}]}}


def test_fireworks_repairs_rejected_baseten_order_with_one_grounded_attempt():
    model = RepairModel()
    orchestrator = SparkWarehouseOrchestrator(None, model)
    spec = orchestrator.parse_natural_language_order_via_spark("Cut 5 circles of 20mm from 3mm SS304 sheet, kerf 1mm.")
    assert spec.parts[0].quantity == 5
    assert [c["prefer_provider"] for c in model.calls] == ["baseten", "fireworks"]
    assert model.calls[-1]["failover"] is False
    assert orchestrator.last_llm_trace["repair_attempted"]


def test_repair_cannot_override_requirements_or_loop_indefinitely():
    model = RepairModel(corrected=False)
    with pytest.raises(ValueError, match="ERR_ORDER_NEEDS_CLARIFICATION"):
        SparkWarehouseOrchestrator(None, model).parse_natural_language_order_via_spark(
            "Cut 5 circles of 20mm from 3mm SS304 sheet, kerf 1mm.")
    assert len(model.calls) == 2
    model = RepairModel()
    with pytest.raises(ValueError, match="ERR_ORDER_NEEDS_CLARIFICATION"):
        SparkWarehouseOrchestrator(None, model).parse_natural_language_order_via_spark("Cut 5 circles of 20mm from SS304 sheet.")
    assert model.calls == []
