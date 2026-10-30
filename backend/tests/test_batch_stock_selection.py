from fastapi.testclient import TestClient
from shapely.geometry import box
from backend.api import create_app

def test_selected_batches_restrict_real_nesting_and_never_fall_back(tmp_path):
    client = TestClient(create_app(str(tmp_path / "stock.db"), str(tmp_path / "artifacts")))
    db = client.app.state.db
    for name in ["BATCH_A_SHEET", "BATCH_B_SHEET"]:
        db.upsert_remnant(name, "cardboard", 3, box(0, 0, 120, 120))
    request = {
        "order": {"material": "cardboard", "thickness_mm": 3, "kerf_mm": 1,
                  "parts": [{"part_id": "disc", "shape_type": "circle", "diameter_mm": 20, "quantity": 2}]},
        "selected_sheet_ids": ["BATCH_B_SHEET"], "search_iterations": 0,
        "plan_id": "selection-plan-001"
    }
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert response.status_code == 200, response.text
    result = response.json()
    assert [s["sheet_id"] for s in result["candidate_sheets"]] == ["BATCH_B_SHEET"]
    assert all(s["sheet_id"] == "BATCH_B_SHEET" for s in result["nesting"]["sheet_outcomes"])
    assert result["nesting"]["total_placed"] == 2
    assert all(p["verification"]["verified_safe"] for p in result["gcode_programs"])
    assert client.post("/api/v1/execute-pipeline", json=request).json() == result
    # Changing scope cannot replay another batch's saved program.
    changed = client.post("/api/v1/execute-pipeline", json={**request, "selected_sheet_ids": ["BATCH_A_SHEET"]})
    assert changed.status_code != 200
    for ids in [[], ["NOT_IN_INVENTORY"]]:
        missing = client.post("/api/v1/execute-pipeline", json={**request, "plan_id": None, "selected_sheet_ids": ids})
        assert missing.status_code == 422, missing.text
    assert db.get_remnant("BATCH_A_SHEET").polygon.equals(box(0, 0, 120, 120))
    assert db.get_remnant("BATCH_B_SHEET").polygon.equals(box(0, 0, 120, 120))
