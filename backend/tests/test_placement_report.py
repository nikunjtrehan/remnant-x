"""DXF import success is separate from geometric fit; inventory stays unchanged."""
import pytest
from fastapi.testclient import TestClient
from shapely import affinity
from shapely.geometry import Polygon, box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory


def run_dxf(tmp_path, sheets, part, quantity=1, kerf=1):
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    app.state.llm.chat_completion = lambda **kwargs: {"ok": False, "error": "offline"}
    for name, poly in sheets.items():
        app.state.db.upsert_remnant(name, "ss304", 3, poly)
    fixture = tmp_path / "part.dxf"
    CADPartFactory.save_part_to_dxf(part, str(fixture))
    client = TestClient(app)
    upload = client.post("/api/v1/upload-dxf", files={"file": ("part.dxf", fixture.read_bytes())})
    assert upload.status_code == 200, upload.text
    parsed = client.post("/api/v1/parse-order", json={
        "prompt": f"Cut {quantity} copies of this.", "uploaded_dxf_files": [upload.json()["dxf_path"]],
        "stock": {"material": "ss304", "thickness_mm": 3, "kerf_mm": kerf},
    })
    assert parsed.status_code == 200, parsed.text
    response = client.post("/api/v1/execute-pipeline", json={
        "order": parsed.json()["order"], "search_iterations": 0,
        "plan_id": "placement-report-plan", "machine_profile": "LINUXCNC_LASER",
    })
    assert response.status_code == 200, response.text
    assert all(app.state.db.get_remnant(name).polygon.equals(poly) for name, poly in sheets.items())
    return response.json()


def test_copied_remnant_reports_small_stock_and_identical_outline(tmp_path):
    large = Polygon(box(0, 0, 120, 100).exterior.coords, [box(25, 25, 45, 45).exterior.coords])
    result = run_dxf(tmp_path, {"SMALL": box(0, 0, 60, 50), "LARGE": large}, large)
    assert result["nesting"]["total_placed"] == 0
    assert result["gcode_programs"] == []
    assert "plan_id" not in result
    checks = result["nesting"]["placement_checks"]
    assert [(c["sheet_id"], c["reason"]) for c in checks] == [
        ("SMALL", "INSUFFICIENT_AREA"), ("LARGE", "STOCK_OUTLINE")]
    assert all(c["remaining"] == 1 and c["next_step"] for c in checks)


def test_parts_continue_to_larger_stock_and_skip_unneeded_stock(tmp_path):
    result = run_dxf(tmp_path, {"LAST": box(0, 0, 300, 300), "SMALL": box(0, 0, 40, 40),
                               "LARGE": box(0, 0, 150, 70)}, box(0, 0, 60, 40), quantity=2)
    checks = result["nesting"]["placement_checks"]
    assert [(c["sheet_id"], c["placed"], c["remaining"]) for c in checks] == [
        ("SMALL", 0, 2), ("LARGE", 2, 0)]
    assert result["nesting"]["total_placed"] == 2
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])


def test_partial_order_reports_remaining_capacity_without_saving_a_complete_plan(tmp_path):
    result = run_dxf(tmp_path, {"SHEET": box(0, 0, 88, 70)}, box(0, 0, 60, 50), quantity=3)
    assert result["nesting"]["total_placed"] == 1
    check, = result["nesting"]["placement_checks"]
    assert (check["requested"], check["placed"], check["remaining"]) == (3, 1, 2)
    assert check["reason"] == "INSUFFICIENT_FREE_AREA"
    assert "plan_id" not in result


@pytest.mark.parametrize("width,expected", [(200, "EXCEEDS_REMNANT_SPAN"), (130, "NO_POSITION_FOUND")])
def test_size_proof_does_not_confuse_rotation_with_an_oversized_part(tmp_path, width, expected):
    part = box(0, 0, width, 3)
    result = run_dxf(tmp_path, {"SHEET": box(0, 0, 100, 100)}, part)
    assert result["nesting"]["placement_checks"][0]["reason"] == expected
    if width == 130:
        # A 45-degree pose actually exists; the quarter-turn search missed it.
        rotated = CADPartFactory.normalize_to_origin(affinity.rotate(part, 45))
        assert box(0, 0, 100, 100).buffer(-1).covers(affinity.translate(rotated, 2, 2))


def test_disconnected_free_regions_are_explained(tmp_path):
    sheet = Polygon(box(0, 0, 100, 60).exterior.coords, [box(48, 2, 52, 58).exterior.coords])
    result = run_dxf(tmp_path, {"SHEET": sheet}, box(0, 0, 60, 40), kerf=6)
    assert result["nesting"]["placement_checks"][0]["reason"] == "FRAGMENTED_FREE_SPACE"


def test_zero_clearance_does_not_raise_a_positive_clearance_diagnosis(tmp_path):
    result = run_dxf(tmp_path, {"SHEET": box(0, 0, 100, 100)}, box(0, 0, 100, 100), kerf=0)
    assert result["nesting"]["total_placed"] == 1
    assert result["nesting"]["placement_checks"][0]["reason"] == "PLACED"


def test_all_stock_too_small_is_not_misreported_as_missing_material(tmp_path):
    result = run_dxf(tmp_path, {"SMALL": box(0, 0, 20, 20)}, box(0, 0, 60, 40))
    assert result["nesting"]["total_placed"] == 0
    assert result["nesting"]["placement_checks"][0]["reason"] == "INSUFFICIENT_AREA"
