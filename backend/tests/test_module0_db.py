import os
import pytest
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, RemnantWarehouseDB


def test_smallest_remnant_first_ranking(tmp_path):
    """Scenario 6: Verify warehouse returns smallest compatible scrap sheet first."""
    db_file = str(tmp_path / "test_warehouse.db")
    db = RemnantWarehouseDB(db_path=db_file)

    # Insert 3 sheets: Large (1000x1000), Small (200x200), Medium (500x500)
    db.upsert_remnant(
        "SHEET_LARGE", "steel", 3.0, Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)])
    )
    db.upsert_remnant(
        "SHEET_SMALL", "steel", 3.0, Polygon([(0, 0), (200, 0), (200, 200), (0, 200)])
    )
    db.upsert_remnant(
        "SHEET_MED", "steel", 3.0, Polygon([(0, 0), (500, 0), (500, 500), (0, 500)])
    )

    matches = db.query_compatible_remnants(
        material="steel", thickness_mm=3.0, min_usable_area_mm2=10000.0
    )
    assert [m.sheet_id for m in matches] == [
        "SHEET_SMALL",
        "SHEET_MED",
        "SHEET_LARGE",
    ]


def test_commit_cut_subtracts_parts_into_permanent_holes(tmp_path):
    """Scenario 3: Verify 1-Click 'Commit Cut' permanently subtracts cut parts in SQLite."""
    db_file = str(tmp_path / "test_commit.db")
    db = RemnantWarehouseDB(db_path=db_file)

    # Start with a solid 400x300mm sheet (Area = 120,000 mm2, 0 holes)
    sheet_poly = Polygon([(0, 0), (400, 0), (400, 300), (0, 300)])
    db.upsert_remnant("SHEET_01", "aluminum", 2.0, sheet_poly)

    # Cut two 50x50mm rectangular parts (2,500 mm2 each = 5,000 mm2 total) inside the sheet
    part1 = Polygon([(50, 50), (100, 50), (100, 100), (50, 100)])
    part2 = Polygon([(200, 50), (250, 50), (250, 100), (200, 100)])

    updated = db.commit_cut_to_sheet(
        "SHEET_01", [part1, part2], kerf_mm=0.0
    )

    assert updated.hole_count == 2
    assert abs(updated.usable_area_mm2 - 115000.0) < 1.0


def test_dxf_roundtrip_preserves_inner_holes(tmp_path):
    """Scenario 1 & 2: Verify hollow ring .DXF export and reload preserves the inner cutout hole."""
    dxf_file = str(tmp_path / "hollow_washer.dxf")
    ring_poly, _ = CADPartFactory.make_hollow_ring(
        outer_diam_mm=100.0, inner_diam_mm=40.0
    )

    CADPartFactory.save_part_to_dxf(ring_poly, dxf_file)
    reloaded_poly = CADPartFactory.load_part_from_dxf(dxf_file)

    assert len(reloaded_poly.interiors) == 1
    assert abs(reloaded_poly.area - ring_poly.area) < 5.0
