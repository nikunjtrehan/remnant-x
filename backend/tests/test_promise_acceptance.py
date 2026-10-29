"""Acceptance evidence for recovered application promises, using synthetic inputs."""
from collections import Counter

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely import affinity
from shapely.geometry import Polygon, box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory, CADPartSpec, RemnantRecord
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m3_nfp_nester import HoleAwareNester


def test_asymmetric_part_must_keep_distinct_rotations_with_same_rounded_centroid():
    # A small corner notch scarcely moves the centroid, but changes which way the
    # part fits. Width, height, area and rounded centroid cannot prove symmetry.
    part = Polygon([(0, 0), (10, 0), (10, 9.9), (9.9, 9.9), (9.9, 10), (0, 10)])
    sheet_poly = HoleAwareNester._rotate_and_normalize(part, 270)
    sheet = RemnantRecord("ORIENTED", "steel", 3, sheet_poly.area,
                          sheet_poly.area, 0, sheet_poly, "")
    result = HoleAwareNester(kerf_mm=0, coarse_step_mm=1).nest_batch_across_sheets(
        [sheet], [CADPartSpec("NOTCHED", "notched part", part)])
    assert result.total_placed == 1
    placed = result.sheet_outcomes[0].placed_parts[0]
    assert placed.rotation_deg == 270
    assert placed.polygon.equals(sheet_poly)


def test_independent_sanitizer_checks_outer_edge_clearance():
    valid, reason = HoleAwareNester.verify_placement_sanitizer(
        box(0.1, 5, 10.1, 15), box(0, 0, 30, 30), [], kerf_mm=2)
    assert not valid
    assert reason == "ERR_OUTER_KERF_VIOLATION"


def test_duplicate_station_ids_fail_before_calibration(monkeypatch):
    indexer = RemnantOpticalIndexer(StationCalibrationConfig())
    marker = np.array([[[0, 0], [10, 0], [10, 10], [0, 10]]], dtype=np.float32)

    class DuplicateDetector:
        def detectMarkers(self, image):
            return [marker] * 5, np.array([[0], [1], [2], [3], [0]]), []

    monkeypatch.setattr(indexer, "detector", DuplicateDetector())
    with pytest.raises(ValueError, match="ERR_DUPLICATE_FIDUCIAL"):
        indexer.calibrate_and_flatten(np.zeros((100, 100, 3), dtype=np.uint8))


def test_upload_mixed_holey_cad_batch_over_one_hundred_parts(tmp_path):
    """Two distinct uploads, 105 instances, multiple perforated sheets, exact grade.

    This is a synthetic HTTP integration test, not a 100-file performance claim.
    """
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    client = TestClient(app)
    stock = Polygon(box(0, 0, 120, 80).exterior.coords,
                    holes=[box(50, 25, 70, 55).exterior.coords])
    for sid in ("A", "B", "C"):
        app.state.db.upsert_remnant(sid, "ss304", 3, stock)
    app.state.db.upsert_remnant("WRONG_GRADE", "ss316", 3, stock)

    shapes = {
        "PLATE": Polygon(box(0, 0, 12, 10).exterior.coords,
                         holes=[box(4, 3, 8, 7).exterior.coords]),
        "L_PART": Polygon([(0, 0), (12, 0), (12, 4), (4, 4), (4, 10), (0, 10)]),
    }
    quantities = {"PLATE": 70, "L_PART": 35}
    parts = []
    for name, geometry in shapes.items():
        fixture = tmp_path / (name + ".dxf")
        CADPartFactory.save_part_to_dxf(geometry, str(fixture))
        uploaded = client.post("/api/v1/upload-dxf", files={
            "file": (fixture.name, fixture.read_bytes(), "application/dxf")})
        assert uploaded.status_code == 200, uploaded.text
        parts.append({"part_id": name, "shape_type": "dxf_file",
                      "quantity": quantities[name], "dxf_path": uploaded.json()["dxf_path"]})

    before = {sid: app.state.db.get_remnant(sid).polygon.wkb for sid in ("A", "B", "C", "WRONG_GRADE")}
    response = client.post("/api/v1/execute-pipeline", json={
        "order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1, "parts": parts},
        "coarse_step_mm": 3, "fine_step_mm": 0.5, "commit_cuts_to_db": False})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["nesting"]["total_requested"] == result["nesting"]["total_placed"] == 105
    assert result["nesting"]["sheets_used"] >= 2
    counts = Counter()
    for outcome in result["nesting"]["sheet_outcomes"]:
        placed = []
        for item in outcome["placed_parts"]:
            counts[item["part_id"]] += 1
            geom = item["geometry"]
            poly = Polygon(geom["exterior"], geom["holes"])
            assert stock.covers(poly)
            assert poly.distance(stock.boundary) >= 0.98
            assert len(poly.interiors) == (1 if item["part_id"] == "PLATE" else 0)
            original = shapes[item["part_id"]]
            rotated = HoleAwareNester._rotate_and_normalize(original, item["rotation_deg"])
            expected = affinity.translate(rotated, item["x_mm"], item["y_mm"])
            assert poly.equals_exact(expected, 0.011)
            for previous in placed:
                assert poly.intersection(previous).area == 0
                assert poly.distance(previous) >= 0.98
            placed.append(poly)
    assert counts == quantities
    assert all(program["verification"]["verified_safe"] for program in result["gcode_programs"])
    assert sum(len(program["ordered_loops"]) for program in result["gcode_programs"]) == 175
    assert result["committed_remnants"] == []
    assert all(app.state.db.get_remnant(sid).polygon.wkb == wkb for sid, wkb in before.items())


def test_one_hundred_and_one_distinct_dxf_uploads_feed_one_verified_order(tmp_path):
    app = create_app(str(tmp_path / "warehouse.db"), str(tmp_path / "artifacts"))
    client = TestClient(app)
    stock = Polygon(box(0, 0, 100, 60).exterior.coords,
                    holes=[box(45, 15, 55, 40).exterior.coords])
    for sid in ("A", "B"):
        app.state.db.upsert_remnant(sid, "ss304", 3, stock)
    parts = []
    for i in range(101):
        width, height = 4 + i * 0.01, 3 + (i % 5) * 0.1
        poly = box(0, 0, width, height)
        if i % 10 == 0:
            poly = Polygon(poly.exterior.coords, [box(1, 1, 2, 2).exterior.coords])
        elif i % 10 == 5:
            poly = Polygon([(0, 0), (width, 0), (width, 1), (1, 1), (1, height), (0, height)])
        fixture = tmp_path / f"part_{i}.dxf"
        CADPartFactory.save_part_to_dxf(poly, str(fixture))
        response = client.post("/api/v1/upload-dxf", files={
            "file": (fixture.name, fixture.read_bytes(), "application/dxf")})
        assert response.status_code == 200, response.text
        parts.append({"part_id": f"P_{i}", "shape_type": "dxf_file", "quantity": 1,
                      "dxf_path": response.json()["dxf_path"]})
    assert len({p["dxf_path"] for p in parts}) == 101
    response = client.post("/api/v1/execute-pipeline", json={
        "order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 0.5, "parts": parts},
        "search_iterations": 0, "commit_cuts_to_db": False})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["nesting"]["total_placed"] == result["nesting"]["total_requested"] == 101
    placed = [p for sheet in result["nesting"]["sheet_outcomes"] for p in sheet["placed_parts"]]
    assert {p["part_id"] for p in placed} == {p["part_id"] for p in parts}
    assert sum(len(p["geometry"]["holes"]) for p in placed) == 11
    assert result["nesting"]["search"]["algorithm"] == "nfp_simulated_annealing"
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])
    assert app.state.db.get_remnant("A").polygon.equals(stock)
