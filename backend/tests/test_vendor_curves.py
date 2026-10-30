"""Procedurally generated vendor CAD; no external artwork is distributed."""
import ezdxf
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory


def curved_fixture(path):
    doc = ezdxf.new("R2010")
    doc.units = 5  # centimetres
    msp = doc.modelspace()
    outer = msp.add_spline()
    outer.set_open_uniform([(0, 0, 0), (12, 0, 0), (12, 8, 0), (0, 8, 0), (0, 0, 0)], degree=1)
    outer.closed = True
    for x, y in [(2, 2), (5, 2), (8, 2), (3, 5), (8, 5)]:
        hole = msp.add_spline()
        hole.set_open_uniform([(x, y, 0), (x + 1, y, 0), (x + 1, y + 1, 0), (x, y + 1, 0), (x, y, 0)], degree=3)
        hole.closed = True
    doc.saveas(path)
    return doc


@pytest.mark.parametrize("units,factor", [(0, 1), (1, 25.4), (4, 1), (5, 10), (6, 1000)])
def test_declared_units_convert_geometry_to_mm(tmp_path, units, factor):
    doc = ezdxf.new()
    doc.units = units
    doc.modelspace().add_lwpolyline([(0, 0), (2, 0), (2, 1), (0, 1)], close=True)
    path = tmp_path / "units.dxf"
    doc.saveas(path)
    poly = CADPartFactory.load_part_from_dxf(str(path))
    assert poly.bounds == pytest.approx((0, 0, 2 * factor, factor))
    assert poly.area == pytest.approx(2 * factor ** 2)


def test_splines_keep_five_holes_and_mm_scale_in_canonical_upload(tmp_path):
    fixture = tmp_path / "curves.dxf"
    doc = curved_fixture(fixture)
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    response = TestClient(app).post("/api/v1/upload-dxf", files={"file": ("curves.dxf", fixture.read_bytes())})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["hole_count"] == 5
    assert data["geometry"]["bounds"] == pytest.approx([0, 0, 120, 80])
    assert data["import_info"] == {"source_units": "centimetres", "scale_to_mm": 10,
                                   "spline_count": 6, "curve_tolerance_mm": 0.05}
    canonical = ezdxf.readfile(data["dxf_path"])
    assert canonical.units == 4
    assert {e.dxftype() for e in canonical.modelspace()} == {"LWPOLYLINE"}
    poly = CADPartFactory.load_part_from_dxf(data["dxf_path"])
    loops = [Polygon([(p.x * 10, p.y * 10) for p in e.flattening(0.00001)]) for e in doc.modelspace()]
    reference = Polygon(loops[0].exterior, [p.exterior for p in loops[1:]])
    assert poly.hausdorff_distance(reference) < 0.05


@pytest.mark.parametrize("problem", ["open", "nonplanar", "false_closed"])
def test_splines_do_not_invent_closed_or_planar_contours(tmp_path, problem):
    doc = ezdxf.new()
    doc.units = 4
    spline = doc.modelspace().add_spline()
    if problem == "false_closed":
        spline.set_open_uniform([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], degree=3)
        spline.closed = True
    else:
        spline.set_closed([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], degree=3)
        if problem == "open":
            spline.closed = False
            spline.dxf.flags &= ~2
        else:
            points = list(spline.control_points)
            points[1] = (10, 0, 2)
            spline.control_points = points
    path = tmp_path / "bad.dxf"
    doc.saveas(path)
    with pytest.raises(ValueError, match="ERR_DXF_NOT_PLANAR_CLOSED"):
        CADPartFactory.load_part_from_dxf(str(path))


def test_curved_vendor_copies_spill_from_small_to_large_without_stock_commit(tmp_path):
    fixture = tmp_path / "curves.dxf"
    curved_fixture(fixture)
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    app.state.llm.chat_completion = lambda **kwargs: {"ok": False, "error": "offline"}
    client = TestClient(app)
    stock = {"LARGE": box(0, 0, 600, 180), "SMALL": box(0, 0, 300, 180)}
    for sid, poly in stock.items():
        app.state.db.upsert_remnant(sid, "ss304", 3, poly)
    upload = client.post("/api/v1/upload-dxf", files={"file": ("curves.dxf", fixture.read_bytes())})
    assert upload.status_code == 200, upload.text
    parsed = client.post("/api/v1/parse-order", json={
        "prompt": "I want to cut 10 copies of this.",
        "uploaded_dxf_files": [upload.json()["dxf_path"]],
        "stock": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1}})
    assert parsed.status_code == 200, parsed.text
    planned = client.post("/api/v1/execute-pipeline", json={
        "order": parsed.json()["order"], "search_iterations": 0, "commit_cuts_to_db": False})
    assert planned.status_code == 200, planned.text
    result = planned.json()
    assert [s["sheet_id"] for s in result["candidate_sheets"]] == ["SMALL", "LARGE"]
    assert [(s["sheet_id"], len(s["placed_parts"])) for s in result["nesting"]["sheet_outcomes"]] == [("SMALL", 4), ("LARGE", 6)]
    assert result["nesting"]["total_placed"] == result["nesting"]["total_requested"] == 10
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])
    assert sum(len(p["ordered_loops"]) for p in result["gcode_programs"]) == 60
    assert all(app.state.db.get_remnant(sid).polygon.equals(poly) for sid, poly in stock.items())
