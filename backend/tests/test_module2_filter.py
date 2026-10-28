import pytest
from shapely.geometry import Polygon

from backend.db_and_parts import RemnantWarehouseDB
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import HoleAwareNester


def test_small_order_consumes_smallest_remnant_first(tmp_path):
    """Scenario 6: Verify a 2-circle order consumes the tiny 150x150mm scrap sheet instead of the 1000x1000mm sheet."""
    db = RemnantWarehouseDB(db_path=str(tmp_path / "w_m2.db"))

    db.upsert_remnant(
        "SHEET_GIANT_1000",
        "steel",
        3.0,
        Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000)]),
    )
    db.upsert_remnant(
        "SHEET_MED_500",
        "steel",
        3.0,
        Polygon([(0, 0), (500, 0), (500, 500), (0, 500)]),
    )
    db.upsert_remnant(
        "SHEET_TINY_150",
        "steel",
        3.0,
        Polygon([(0, 0), (150, 0), (150, 150), (0, 150)]),
    )
    db.upsert_remnant(
        "SHEET_WRONG_ALU",
        "aluminum",
        3.0,
        Polygon([(0, 0), (120, 0), (120, 120), (0, 120)]),
    )

    orchestrator = SparkWarehouseOrchestrator(db)
    order_payload = {
        "order_id": "ORD_SMALL_01",
        "material": "Steel",
        "thickness_mm": 3.0,
        "kerf_mm": 2.0,
        "parts": [
            {"part_id": "C50", "shape_type": "circle", "diameter_mm": 50.0, "quantity": 2}
        ],
    }

    order = orchestrator.validate_and_parse_order_dict(order_payload)
    plan = orchestrator.orchestrate_order_plan(order)

    # 1. Verify aluminum was filtered out and steel sheets are ranked Smallest -> Largest
    assert [s.sheet_id for s in plan.candidate_sheets] == [
        "SHEET_TINY_150",
        "SHEET_MED_500",
        "SHEET_GIANT_1000",
    ]

    # 2. Run the plan through Module 3 Nester and prove ONLY SHEET_TINY_150 is touched!
    nester = HoleAwareNester(kerf_mm=plan.kerf_mm)
    nest_res = nester.nest_batch_across_sheets(plan.candidate_sheets, plan.cad_part_specs)

    assert nest_res.status == "COMPLETE"
    assert nest_res.total_placed == 2
    assert nest_res.sheets_used == 1
    assert nest_res.sheet_outcomes[0].sheet_id == "SHEET_TINY_150"


def test_material_and_thickness_isolation(tmp_path):
    """Verify strict filtering by both material grade and sheet thickness tolerance."""
    db = RemnantWarehouseDB(db_path=str(tmp_path / "w_iso.db"))
    db.upsert_remnant("S_STEEL_3MM", "steel", 3.0, Polygon([(0, 0), (300, 0), (300, 300), (0, 300)]))
    db.upsert_remnant("S_ALU_5MM", "aluminum", 5.0, Polygon([(0, 0), (300, 0), (300, 300), (0, 300)]))
    db.upsert_remnant("S_ALU_2MM", "aluminum", 2.0, Polygon([(0, 0), (300, 0), (300, 300), (0, 300)]))

    orchestrator = SparkWarehouseOrchestrator(db)
    order = orchestrator.validate_and_parse_order_dict(
        {
            "order_id": "ORD_ALU2",
            "material": "aluminum",
            "thickness_mm": 2.0,
            "parts": [{"part_id": "R1", "shape_type": "rectangle", "width_mm": 50, "height_mm": 50, "quantity": 1}],
        }
    )
    plan = orchestrator.orchestrate_order_plan(order)
    assert [s.sheet_id for s in plan.candidate_sheets] == ["S_ALU_2MM"]


def test_order_dict_validation_rejects_bad_inputs(tmp_path):
    """Verify fail-closed schema validation on out-of-scope 3D thicknesses or invalid quantities."""
    db = RemnantWarehouseDB(db_path=str(tmp_path / "w_val.db"))
    orchestrator = SparkWarehouseOrchestrator(db)

    # Reject >50mm thickness (3D block out of scope)
    with pytest.raises(ValueError, match="ERR_INVALID_THICKNESS"):
        orchestrator.validate_and_parse_order_dict(
            {"material": "steel", "thickness_mm": 85.0, "parts": [{"shape_type": "circle", "diameter_mm": 20}]}
        )

    # Reject zero/negative part quantity
    with pytest.raises(ValueError, match="ERR_INVALID_QUANTITY"):
        orchestrator.validate_and_parse_order_dict(
            {
                "material": "steel",
                "thickness_mm": 3.0,
                "parts": [{"shape_type": "circle", "diameter_mm": 20, "quantity": 0}],
            }
        )


def test_end_to_end_orchestrator_to_multi_sheet_nester(tmp_path):
    """Verify mixed parametric order (L-brackets + rings + circles) compiles and nests cleanly."""
    db = RemnantWarehouseDB(db_path=str(tmp_path / "w_e2e.db"))
    db.upsert_remnant("S_MAIN", "steel", 3.0, Polygon([(0, 0), (350, 0), (350, 250), (0, 250)]))

    orchestrator = SparkWarehouseOrchestrator(db)
    order = orchestrator.validate_and_parse_order_dict(
        {
            "order_id": "ORD_MIXED",
            "material": "steel",
            "thickness_mm": 3.0,
            "kerf_mm": 2.0,
            "parts": [
                {"part_id": "RING1", "shape_type": "ring", "outer_diam_mm": 120.0, "inner_diam_mm": 80.0, "quantity": 1},
                {"part_id": "LBRK", "shape_type": "l_bracket", "width_mm": 80.0, "height_mm": 80.0, "thickness_leg_mm": 20.0, "quantity": 2},
                {"part_id": "DISK", "shape_type": "circle", "diameter_mm": 40.0, "quantity": 3},
            ],
        }
    )

    plan = orchestrator.orchestrate_order_plan(order)
    assert plan.total_parts_count == 6

    nester = HoleAwareNester(kerf_mm=plan.kerf_mm)
    res = nester.nest_batch_across_sheets(plan.candidate_sheets, plan.cad_part_specs)
    assert res.status == "COMPLETE"
    assert res.total_placed == 6
