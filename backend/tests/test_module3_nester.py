import pytest
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, CADPartSpec, RemnantRecord
from backend.m3_nfp_nester import HoleAwareNester


def _make_l_hole_sheet() -> RemnantRecord:
    """Creates a 400x300mm sheet with a central L-shaped cutout hole."""
    outer = [(0, 0), (400, 0), (400, 300), (0, 300)]
    l_hole = [
        (140, 80),
        (260, 80),
        (260, 140),
        (200, 140),
        (200, 220),
        (140, 220),
    ]
    poly = Polygon(shell=outer, holes=[l_hole])
    return RemnantRecord(
        sheet_id="SHEET_L_HOLE",
        material="steel",
        thickness_mm=3.0,
        outer_area_mm2=120000.0,
        usable_area_mm2=round(float(poly.area), 2),
        hole_count=1,
        polygon=poly,
        dxf_path="",
    )


def test_zero_hole_overlap_and_kerf_clearance():
    """Test Case 1: Verify 0.00 mm2 hole overlap and >= 3.0mm kerf clearance around an L-hole."""
    sheet = _make_l_hole_sheet()
    c_poly, c_name = CADPartFactory.make_circle(diameter_mm=50.0)
    r_poly, r_name = CADPartFactory.make_rectangle(width_mm=70.0, height_mm=40.0)

    specs = [
        CADPartSpec(part_id="P_RECT", name=r_name, polygon=r_poly, quantity=6),
        CADPartSpec(part_id="P_CIRC", name=c_name, polygon=c_poly, quantity=6),
    ]

    nester = HoleAwareNester(kerf_mm=3.0, coarse_step_mm=8.0, fine_step_mm=1.0)
    res = nester.nest_batch_across_sheets([sheet], specs)

    assert res.status == "COMPLETE"
    assert res.total_placed == 12
    assert res.sanitizer_verified is True

    placed = res.sheet_outcomes[0].placed_parts
    l_hole_poly = Polygon(sheet.polygon.interiors[0])

    for i, p1 in enumerate(placed):
        # 0.00 mm2 overlap with the L-shaped hole
        assert p1.polygon.intersection(l_hole_poly).area == 0.0
        # Minimum 3.0mm kerf distance from the L-shaped hole (within 0.15mm discretization tolerance)
        assert p1.polygon.distance(l_hole_poly) >= 2.85

        # 0.00 mm2 overlap with every other placed part
        for j in range(i + 1, len(placed)):
            p2 = placed[j]
            assert p1.polygon.intersection(p2.polygon).area == 0.0
            assert p1.polygon.distance(p2.polygon) >= 2.85


def test_rotation_unlocks_narrow_vertical_strip_and_respects_grain_lock():
    """Test Case 2 (Scenario 5): Verify 90-deg rotation fits narrow strip unless grain_locked=True."""
    # Narrow vertical remnant strip: 60mm wide x 180mm tall
    strip_poly = Polygon([(0, 0), (60, 0), (60, 180), (0, 180)])
    sheet = RemnantRecord(
        sheet_id="STRIP_01",
        material="aluminum",
        thickness_mm=2.0,
        outer_area_mm2=10800.0,
        usable_area_mm2=10800.0,
        hole_count=0,
        polygon=strip_poly,
        dxf_path="",
    )

    # Part is defined horizontally: 140mm wide x 40mm tall
    bar_poly, bar_name = CADPartFactory.make_rectangle(width_mm=140.0, height_mm=40.0)

    # 1. With grain_locked=True (only 0, 180 deg allowed), it MUST NOT fit
    locked_spec = CADPartSpec(
        part_id="BAR_LOCKED", name=bar_name, polygon=bar_poly, quantity=1, grain_locked=True
    )
    nester = HoleAwareNester(kerf_mm=2.0)
    res_locked = nester.nest_batch_across_sheets([sheet], [locked_spec])
    assert res_locked.total_placed == 0

    # 2. With grain_locked=False, it rotates 90 deg and fits cleanly
    free_spec = CADPartSpec(
        part_id="BAR_FREE", name=bar_name, polygon=bar_poly, quantity=1, grain_locked=False
    )
    res_free = nester.nest_batch_across_sheets([sheet], [free_spec])
    assert res_free.total_placed == 1
    assert res_free.sheet_outcomes[0].placed_parts[0].rotation_deg in (90.0, 270.0)


def test_donut_hole_reuse_nests_small_circle_inside_ring():
    """Test Case 3 (Scenario 2): Verify a small circle nests INSIDE the hollow center of a placed ring."""
    # Sheet is 180x180mm. Big ring is 160mm OD / 110mm ID (fills the whole sheet exterior!)
    sheet_poly = Polygon([(0, 0), (180, 0), (180, 180), (0, 180)])
    sheet = RemnantRecord(
        sheet_id="SHEET_DONUT",
        material="steel",
        thickness_mm=3.0,
        outer_area_mm2=32400.0,
        usable_area_mm2=32400.0,
        hole_count=0,
        polygon=sheet_poly,
        dxf_path="",
    )

    ring_poly, ring_name = CADPartFactory.make_hollow_ring(
        outer_diam_mm=160.0, inner_diam_mm=110.0
    )
    small_circle_poly, c_name = CADPartFactory.make_circle(diameter_mm=45.0)

    specs = [
        CADPartSpec(part_id="BIG_RING", name=ring_name, polygon=ring_poly, quantity=1),
        CADPartSpec(part_id="INNER_DISK", name=c_name, polygon=small_circle_poly, quantity=1),
    ]

    nester = HoleAwareNester(kerf_mm=3.0, coarse_step_mm=6.0, fine_step_mm=1.0)
    res = nester.nest_batch_across_sheets([sheet], specs)

    # Both the giant ring AND the 45mm disk must fit on the single 180x180mm sheet!
    assert res.status == "COMPLETE"
    assert res.total_placed == 2
    placed_ring = next(p for p in res.sheet_outcomes[0].placed_parts if p.part_id == "BIG_RING")
    placed_disk = next(p for p in res.sheet_outcomes[0].placed_parts if p.part_id == "INNER_DISK")

    # Zero overlap between the solid ring metal and the inner disk
    assert placed_ring.polygon.intersection(placed_disk.polygon).area == 0.0
    # And the inner disk sits completely inside the outer bounding contour of the ring!
    ring_outer_contour = Polygon(placed_ring.polygon.exterior.coords)
    assert ring_outer_contour.contains(placed_disk.polygon)


def test_skip_and_backfill_multi_sheet_spillover():
    """Test Case 4 (Scenario 7): Verify multi-sheet spillover + small-part backfill on Sheet #1."""
    poly1 = Polygon([(0, 0), (190, 0), (190, 190), (0, 190)])
    poly2 = Polygon([(0, 0), (190, 0), (190, 190), (0, 190)])
    sheets = [
        RemnantRecord("S1", "steel", 3.0, 36100.0, 36100.0, 0, poly1, ""),
        RemnantRecord("S2", "steel", 3.0, 36100.0, 36100.0, 0, poly2, ""),
    ]

    # Request 5 big 80x80mm plates (only 4 can physically fit on a 190x190mm sheet -> 5th spills to S2)
    # Plus 4 tiny 20x20mm washers (which should backfill the remaining 20mm strip on S1!)
    big_poly, big_name = CADPartFactory.make_rectangle(80.0, 80.0)
    tiny_poly, tiny_name = CADPartFactory.make_rectangle(20.0, 20.0)

    specs = [
        CADPartSpec(part_id="BIG_80", name=big_name, polygon=big_poly, quantity=5),
        CADPartSpec(part_id="TINY_20", name=tiny_name, polygon=tiny_poly, quantity=4),
    ]

    nester = HoleAwareNester(kerf_mm=2.0, coarse_step_mm=5.0, fine_step_mm=1.0)
    res = nester.nest_batch_across_sheets(sheets, specs)

    assert res.status == "COMPLETE"
    assert res.total_placed == 9
    assert res.sheets_used == 2

    # Sheet 1 should hold 4 BIG_80 plates AND all 4 TINY_20 washers (Skip & Backfill!)
    s1_parts = [p.part_id for p in res.sheet_outcomes[0].placed_parts]
    assert s1_parts.count("BIG_80") == 4
    assert s1_parts.count("TINY_20") == 4

    # Sheet 2 holds the 5th spilled-over BIG_80 plate
    s2_parts = [p.part_id for p in res.sheet_outcomes[1].placed_parts]
    assert s2_parts == ["BIG_80"]


def test_nfp_budget_fallback_keeps_stock_holes_and_clearance(monkeypatch):
    def over_budget(*args):
        raise ValueError("ERR_NFP_COMPLEXITY: convex-pair limit is 20000")
    monkeypatch.setattr("backend.m3_nfp_nester.no_fit_polygon", over_budget)
    sheet = _make_l_hole_sheet()
    poly, name = CADPartFactory.make_rectangle(60, 40)
    nester = HoleAwareNester(kerf_mm=2, fine_step_mm=2)
    result = nester.nest_batch_across_sheets(
        [sheet], [CADPartSpec("P", name, poly, quantity=10)])
    assert result.total_placed == result.total_requested == 10
    assert result.search_trace["complexity_fallback"] == "bounded_grid"
    assert result.search_trace["grid_max_positions_per_orientation"] == 10201
    placed = result.sheet_outcomes[0].placed_parts
    for index, part in enumerate(placed):
        assert sheet.polygon.covers(part.polygon)
        assert part.polygon.distance(sheet.polygon.boundary) >= 2 - 1e-6
        assert nester.verify_placement_sanitizer(part.polygon, sheet.polygon, placed[:index], 2)[0]
