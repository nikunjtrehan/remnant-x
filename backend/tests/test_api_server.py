from fastapi.testclient import TestClient
import pytest

from backend.api import create_app


@pytest.mark.parametrize("prompt,quantity", [
    ("Cut 3 circles of 20mm from 3mm steel sheet, kerf 1mm", 3),
    ("Cut 2 steel hollow rings with 120mm outer diameter and 60mm inner diameter, plus 2 solid circles of 45mm diameter from 3mm steel sheet.", 4),
])
def test_ui_can_execute_simple_and_mixed_prompts(tmp_path, prompt, quantity):
    client = TestClient(create_app(str(tmp_path / "prompts.db")))
    client.post("/api/v1/seed-demo-warehouse")
    response = client.post("/api/v1/execute-pipeline", json={
        "prompt": prompt, "allow_demo_stock": True,
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["nesting"]["total_requested"] == quantity
    assert result["nesting"]["total_placed"] == quantity
    assert result["committed_remnants"] == []  # UI previews do not consume stock.
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])


def test_api_health_and_seed_warehouse(tmp_path):
    db_file = str(tmp_path / "test_api.db")
    app = create_app(db_path=db_file)
    client = TestClient(app)

    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    data = r_health.json()
    assert data["status"] == "ok"
    assert "providers" in data

    r_seed = client.post("/api/v1/seed-demo-warehouse")
    assert r_seed.status_code == 200
    seed_data = r_seed.json()
    assert seed_data["seeded_count"] == 3

    r_list = client.get("/api/v1/remnants?material=steel&thickness_mm=3.0")
    assert r_list.status_code == 200
    list_data = r_list.json()
    assert list_data["count"] == 2
    # Verify smallest usable remnant comes first
    areas = [rem["usable_area_mm2"] for rem in list_data["remnants"]]
    assert areas == sorted(areas)


def test_api_upsert_custom_remnant(tmp_path):
    db_file = str(tmp_path / "test_upsert.db")
    app = create_app(db_path=db_file)
    client = TestClient(app)

    payload = {
        "sheet_id": "REM_CUSTOM_01",
        "material": "steel",
        "thickness_mm": 3.0,
        "exterior": [[0, 0], [300, 0], [300, 200], [0, 200]],
        "holes": [[[50, 50], [100, 50], [100, 100], [50, 100]]],
    }
    resp = client.post("/api/v1/remnants", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["remnant"]["sheet_id"] == "REM_CUSTOM_01"
    assert body["remnant"]["hole_count"] == 1
    assert body["remnant"]["usable_area_mm2"] == 57500.0


def test_api_execute_full_pipeline_structured_and_commit(tmp_path):
    db_file = str(tmp_path / "test_pipeline.db")
    app = create_app(db_path=db_file)
    client = TestClient(app)

    client.post("/api/v1/seed-demo-warehouse")

    req_payload = {
        "order": {
            "order_id": "ORD_API_DONUT",
            "material": "steel",
            "thickness_mm": 3.0,
            "kerf_mm": 3.0,
            "parts": [
                {
                    "part_id": "RING_01",
                    "shape_type": "ring",
                    "quantity": 1,
                    "outer_diam_mm": 110.0,
                    "inner_diam_mm": 64.0,
                },
                {
                    "part_id": " PIN_01",
                    "shape_type": "circle",
                    "quantity": 1,
                    "diameter_mm": 36.0,
                },
            ],
        },
        "coarse_step_mm": 8.0,
        "fine_step_mm": 2.0,
        "commit_cuts_to_db": True,
        "allow_demo_stock": True,
    }

    resp = client.post("/api/v1/execute-pipeline", json=req_payload)
    assert resp.status_code == 200
    res = resp.json()

    assert res["nesting"]["total_requested"] == 2
    assert res["nesting"]["total_placed"] == 2
    assert res["nesting"]["sanitizer_verified"] is True
    assert len(res["gcode_programs"]) >= 1
    assert res["gcode_programs"][0]["verification"]["verified_safe"] is True
    assert res["gcode_programs"][0]["verification"]["inside_out_order_valid"] is True
    assert len(res["committed_remnants"]) >= 1
