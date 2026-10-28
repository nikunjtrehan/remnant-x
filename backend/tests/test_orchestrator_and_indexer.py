import numpy as np
from shapely.geometry import Polygon

from backend.db_and_parts import RemnantWarehouseDB
from backend.llm_client import LiveModelClient
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.m3_nfp_nester import PlacedPartInstance
from backend.m4_muse_gcode import GCodeCompiler


def test_llm_client_json_extractor_handles_fences_and_raw():
    raw_fenced = 'Here is the output:\n```json\n{"material": "steel", "thickness_mm": 3.0}\n```'
    parsed = LiveModelClient.extract_json(raw_fenced)
    assert parsed is not None
    assert parsed["material"] == "steel"
    assert parsed["thickness_mm"] == 3.0


def test_m1_fetch_sam3_mask_extracts_clean_binary_topology():
    cfg = StationCalibrationConfig()
    indexer = RemnantOpticalIndexer(cfg)

    # Create a synthetic 1200x900 warped canvas (black station = 0, bright remnant = 240)
    canvas = np.zeros((900, 1200, 3), dtype=np.uint8)
    canvas[200:700, 250:950] = (240, 240, 240)
    # Punch an interior rectangular hole inside the remnant
    canvas[350:500, 450:650] = (0, 0, 0)

    mask = indexer.fetch_sam3_mask(canvas, use_live_vision_audit=False, segmentation_mode="local_threshold")
    poly = indexer.build_topological_polygon(mask)

    assert poly.is_valid
    assert len(poly.interiors) == 1
    assert poly.area > 60000.0


def test_natural_language_order_with_offline_fallback():
    db = RemnantWarehouseDB(":memory:")
    orch = SparkWarehouseOrchestrator(db)

    prompt = (
        "Cut 2 steel hollow rings with 120mm outer diameter and 60mm inner diameter, "
        "plus 2 solid circles of 45mm diameter from 3mm steel sheet."
    )
    spec = orch.parse_natural_language_order_via_spark(prompt)

    assert spec.material == "steel"
    assert spec.thickness_mm == 3.0
    assert len(spec.parts) == 2
    assert orch.last_llm_trace["ok"] is True


def test_grbl_profile_preserves_verified_coordinates():
    compiler = GCodeCompiler()
    sheet_poly = Polygon([(0, 0), (300, 0), (300, 200), (0, 200)])
    part_poly = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])

    placed = [
        PlacedPartInstance(
            instance_id="RECT_01",
            part_id="P_01",
            name="Rect_60x60",
            sheet_id="REM_TEST_01",
            x_mm=20.0,
            y_mm=20.0,
            rotation_deg=0.0,
            polygon=part_poly,
        )
    ]

    compiled = compiler.compile_iso_gcode("REM_TEST_01", sheet_poly, placed)
    assert compiled.verification.verified_safe is True

    post_gcode = compiler.apply_machine_profile(
        "ISO_6983_GRBL",
        compiled_gcode=compiled,
    )
    assert "PROFILE: ISO_6983_GRBL" in post_gcode
    assert "G01 X80.000 Y20.000" in post_gcode
    assert compiler.last_llm_trace["ok"] is True


def test_m2_upgrade1_synonyms_square_autofill_and_vendor_dxf_batch(tmp_path):
    from backend.db_and_parts import CADPartFactory

    # Create a complex vendor DXF file on disk (a hollow ring with interior hole)
    vendor_poly, _ = CADPartFactory.make_hollow_ring(90.0, 40.0)
    vendor_dxf_path = str(tmp_path / "vendor_clutch_plate.dxf")
    CADPartFactory.save_part_to_dxf(vendor_poly, vendor_dxf_path)

    raw_payload = {
        "order_id": "ORD_VENDOR_BATCH",
        "material": "Stainless Steel 304",
        "thickness_mm": 3.0,
        "parts": [
            {
                "part_id": "WASH_01",
                "shape_type": "washer",
                "quantity": 4,
                "outer_diam_mm": 80.0,
                "inner_diam_mm": 35.0,
            },
            {
                "part_id": "DISC_01",
                "shape_type": "disc",
                "quantity": 4,
                "diameter_mm": 25.0,
            },
            {
                "part_id": "SQ_01",
                "shape_type": "square",
                "quantity": 2,
                "width_mm": 60.0,
                "height_mm": 0.0,
            },
            {
                "part_id": "VENDOR_CAD_01",
                "shape_type": "uploaded_file",
                "quantity": 50,
            },
        ],
    }

    spec = SparkWarehouseOrchestrator.validate_and_parse_order_dict(
        raw_payload, uploaded_dxf_files=[vendor_dxf_path]
    )
    assert spec.material == "ss304"
    assert spec.parts[0].shape_type == "ring"
    assert spec.parts[1].shape_type == "circle"
    assert spec.parts[2].shape_type == "rectangle"
    assert spec.parts[2].width_mm == 60.0 and spec.parts[2].height_mm == 60.0
    assert spec.parts[3].shape_type == "dxf_file"
    assert spec.parts[3].quantity == 50
    assert spec.parts[3].dxf_path == vendor_dxf_path

    cad_specs = SparkWarehouseOrchestrator.build_cad_part_specs(spec)
    assert len(cad_specs) == 4
    assert cad_specs[3].quantity == 50
    assert len(cad_specs[3].polygon.interiors) == 1


def test_m2_upgrade2_offline_regex_fallback_when_all_clouds_down(tmp_path):
    from backend.db_and_parts import CADPartFactory

    vendor_poly, _ = CADPartFactory.make_rectangle(75.0, 45.0)
    vendor_dxf = str(tmp_path / "custom_gear.dxf")
    CADPartFactory.save_part_to_dxf(vendor_poly, vendor_dxf)

    db = RemnantWarehouseDB(":memory:")
    offline_llm = LiveModelClient()
    # Simulate complete venue Wi-Fi outage / all cloud keys offline
    offline_llm.baseten_api_key = ""
    offline_llm.fireworks_api_key = ""
    offline_llm.meta_api_key = ""

    orch = SparkWarehouseOrchestrator(db, llm_client=offline_llm)
    prompt = (
        "Cut 50 of the uploaded dxf file, plus 2 stainless steel washers with "
        "120mm outer diameter and 60mm inner diameter, and 2 solid discs of 45mm "
        "from 3mm stainless steel sheet."
    )
    spec = orch.parse_natural_language_order_via_spark(
        prompt, uploaded_dxf_files=[vendor_dxf]
    )

    assert spec.material == "stainless_steel"
    assert spec.thickness_mm == 3.0
    assert len(spec.parts) == 3
    assert spec.parts[0].shape_type == "dxf_file" and spec.parts[0].quantity == 50
    assert spec.parts[1].shape_type == "ring" and spec.parts[1].quantity == 2
    assert spec.parts[2].shape_type == "circle" and spec.parts[2].quantity == 2
    assert orch.last_llm_trace["provider"] == "local-deterministic-fallback"
