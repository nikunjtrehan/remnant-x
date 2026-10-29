import pytest
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, CADPartSpec, RemnantRecord
from backend.m3_nfp_nester import HoleAwareNester
from backend.m4_muse_gcode import GCodeCompiler


def test_inside_out_cut_order_and_donut_hierarchy():
    """Scenario 1 & 2: When a disk is nested inside a hollow ring, verify exact cut order:

      Loop 1 -> INNER_DISK (outer perimeter)
      Loop 2 -> BIG_RING (internal hole)
      Loop 3 -> BIG_RING (outer perimeter)
    """
    sheet_poly = Polygon([(0, 0), (180, 0), (180, 180), (0, 180)])
    sheet = RemnantRecord("S_DONUT", "steel", 3.0, 32400.0, 32400.0, 0, sheet_poly, "")

    ring_poly, r_name = CADPartFactory.make_hollow_ring(160.0, 110.0)
    disk_poly, d_name = CADPartFactory.make_circle(45.0)

    specs = [
        CADPartSpec("BIG_RING", r_name, ring_poly, quantity=1),
        CADPartSpec("INNER_DISK", d_name, disk_poly, quantity=1),
    ]

    nester = HoleAwareNester(kerf_mm=3.0, coarse_step_mm=6.0, fine_step_mm=1.0)
    nest_res = nester.nest_batch_across_sheets([sheet], specs)
    placed = nest_res.sheet_outcomes[0].placed_parts

    compiler = GCodeCompiler()
    compiled = compiler.compile_iso_gcode("S_DONUT", sheet_poly, placed)

    assert compiled.verification.verified_safe is True
    assert compiled.verification.inside_out_order_valid is True
    assert len(compiled.ordered_loops) == 3

    # Verify exact sequence: Inner Disk -> Ring Internal Hole -> Ring Outer Perimeter
    assert compiled.ordered_loops[0].instance_id.startswith("INNER_DISK")
    assert compiled.ordered_loops[0].loop_type == "OUTER_PERIMETER"

    assert compiled.ordered_loops[1].instance_id.startswith("BIG_RING")
    assert compiled.ordered_loops[1].loop_type == "INTERNAL_HOLE"

    assert compiled.ordered_loops[2].instance_id.startswith("BIG_RING")
    assert compiled.ordered_loops[2].loop_type == "OUTER_PERIMETER"


def test_physical_corner_origin_shift():
    """Scenario 4: Verify G-Code coordinates shift relative to the sheet's physical (min_x, min_y) corner."""
    # Sheet sitting at offset (X=120..320mm, Y=85..285mm) on the indexing table
    offset_sheet_poly = Polygon([(120, 85), (320, 85), (320, 285), (120, 285)])
    sheet = RemnantRecord("S_OFFSET", "steel", 3.0, 40000.0, 40000.0, 0, offset_sheet_poly, "")

    rect_poly, r_name = CADPartFactory.make_rectangle(50.0, 40.0)
    specs = [CADPartSpec("R50", r_name, rect_poly, quantity=1)]

    nester = HoleAwareNester(kerf_mm=2.0)
    nest_res = nester.nest_batch_across_sheets([sheet], specs)

    compiler = GCodeCompiler()
    compiled = compiler.compile_iso_gcode(
        "S_OFFSET", offset_sheet_poly, nest_res.sheet_outcomes[0].placed_parts, shift_to_sheet_corner=True
    )

    assert compiled.origin_x_mm == 120.0
    assert compiled.origin_y_mm == 85.0
    assert compiled.verification.verified_safe is True
    # Since the 50x40 part nests near the bottom-left corner of the 200x200 sheet,
    # its shifted coordinates must lie within [0..60mm], NOT [120..180mm]!
    for vx, vy in compiled.ordered_loops[0].coords_mm:
        assert 0.0 <= vx <= 60.0
        assert 0.0 <= vy <= 50.0


def test_gcode_verifier_catches_rogue_hole_cut():
    """Verify that verify_gcode_toolpath catches a laser cut passing through an interior sheet hole."""
    outer = [(0, 0), (300, 0), (300, 300), (0, 300)]
    hole = [(100, 100), (200, 100), (200, 200), (100, 200)]
    sheet_poly = Polygon(shell=outer, holes=[hole])

    # Rogue G-Code that turns laser ON (M03) at (50, 150) and cuts straight across the hole to (250, 150)
    rogue_gcode = "\n".join(
        [
            "G21",
            "G90",
            "G94",
            "M05",
            "G00 X50.000 Y150.000",
            "M03 S1000",
            "G01 X250.000 Y150.000 F1800.0",
            "M05",
        ]
    )

    report = GCodeCompiler.verify_gcode_toolpath(
        gcode_text=rogue_gcode, shifted_sheet_poly=sheet_poly, ordered_loops=[]
    )
    assert report.verified_safe is False
    assert report.hole_collision_length_mm > 90.0


def test_full_pipeline_l_hole_sheet_to_verified_gcode():
    """End-to-End Local Math Check: L-Hole Sheet -> Nester -> G-Code Compiler -> Collision Verifier."""
    outer = [(0, 0), (400, 0), (400, 300), (0, 300)]
    l_hole = [(140, 80), (260, 80), (260, 140), (200, 140), (200, 220), (140, 220)]
    sheet_poly = Polygon(shell=outer, holes=[l_hole])
    sheet = RemnantRecord(
        "S_L_HOLE", "steel", 3.0, 120000.0, float(sheet_poly.area), 1, sheet_poly, ""
    )

    c_poly, c_name = CADPartFactory.make_circle(45.0)
    w_poly, w_name = CADPartFactory.make_hollow_ring(60.0, 25.0)
    specs = [
        CADPartSpec("WASHER", w_name, w_poly, quantity=3),
        CADPartSpec("DISK", c_name, c_poly, quantity=4),
    ]

    nester = HoleAwareNester(kerf_mm=3.0)
    nest_res = nester.nest_batch_across_sheets([sheet], specs)
    assert nest_res.status == "COMPLETE"

    compiler = GCodeCompiler()
    compiled = compiler.compile_iso_gcode(
        "S_L_HOLE", sheet_poly, nest_res.sheet_outcomes[0].placed_parts
    )

    assert compiled.verification.verified_safe is True
    assert compiled.verification.hole_collision_length_mm == 0.0
    assert compiled.verification.outside_sheet_length_mm == 0.0
    assert compiled.verification.inside_out_order_valid is True
    assert compiled.verification.active_cut_loops_count == (3 * 2) + 4  # 3 washers (2 loops each) + 4 disks
