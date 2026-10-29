import copy
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box
from backend.api import create_app
from backend.m1_sam_indexer import RemnantOpticalIndexer
from backend.m3_nfp_nester import HoleAwareNester
from backend.review_workflow import confirm_plan, save_plan
from backend.tests.test_photo_preflight import photo_payload


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path / "test.db"), str(tmp_path / "artifacts")))


def scan(client, **updates):
    payload = {**photo_payload(), "sheet_id": "RX-001", "material": "SS304", "thickness_mm": 3,
               "save_to_warehouse": False, "segmentation_mode": "local_threshold",
               "review_id": "review-001", "location": "Rack B / slot 3", **updates}
    response = client.post("/api/v1/index-remnant", json=payload)
    assert response.status_code == 200, response.text
    return payload, response.json()


def test_geometry_requires_review_and_acceptance_is_replay_safe(client, monkeypatch):
    payload, result = scan(client)
    assert not result["saved_remnant"]
    assert result["review_status"] == "pending"
    assert result["review_image_base64"].startswith("data:image/jpeg;base64,")
    assert client.get("/api/v1/remnants").json()["remnants"] == []
    monkeypatch.setattr(RemnantOpticalIndexer, "fetch_sam3_mask",
                        lambda *a, **k: pytest.fail("Retry must reuse the analysis"))
    assert client.post("/api/v1/index-remnant", json=payload).json() == result
    changed = client.post("/api/v1/index-remnant", json={**payload, "material": "SS316"})
    assert changed.status_code == 422 and "INPUT_CHANGED" in changed.text
    accepted = client.post("/api/v1/intake-reviews/review-001/accept").json()
    assert accepted["saved_remnant"]["material"] == "ss304"
    assert accepted["saved_remnant"]["location"] == "Rack B / slot 3"
    assert client.post("/api/v1/intake-reviews/review-001/accept").json() == accepted
    assert len(client.get("/api/v1/remnants").json()["remnants"]) == 1
    assert client.get("/api/v1/intake-reviews").json()["reviews"] == []


def test_rejection_and_physical_id_collision_cannot_replace_stock(client):
    scan(client)
    assert client.get("/api/v1/intake-reviews").json()["reviews"][0]["fields"]["sheet_id"] == "RX-001"
    db = client.app.state.db
    existing = db.upsert_remnant("RX-001", "ss316", 4, box(0, 0, 60, 60))
    assert client.post("/api/v1/intake-reviews/review-001/accept").status_code == 409
    assert db.get_remnant("RX-001").polygon.equals(existing.polygon)
    assert db.get_remnant("RX-001").material == "ss316"
    assert client.post("/api/v1/intake-reviews/review-001/reject").status_code == 200
    assert client.post("/api/v1/intake-reviews/review-001/accept").status_code == 409
    assert client.get("/api/v1/intake-reviews").json()["reviews"] == []


def test_review_survives_api_restart_and_cannot_accept_cropped_geometry(client, tmp_path):
    scan(client)
    restarted = TestClient(create_app(str(tmp_path / "test.db"), str(tmp_path / "artifacts")))
    result = restarted.get("/api/v1/intake-reviews/review-001").json()
    assert result["review_status"] == "pending"
    import json
    with restarted.app.state.db._connect() as conn:
        result["review_blocked"] = True
        conn.execute("UPDATE intake_reviews SET payload=? WHERE review_id=?", (json.dumps(result), "review-001"))
    response = restarted.post("/api/v1/intake-reviews/review-001/accept")
    assert response.status_code == 409 and "CAPTURE_TRUNCATED" in response.text
    assert restarted.get("/api/v1/remnants").json()["remnants"] == []


def planned(client):
    client.app.state.db.upsert_remnant("RX-PLAN", "steel", 3, box(0, 0, 180, 120), location="Rack A")
    request = {"plan_id": "plan-001", "order": {"material": "steel", "thickness_mm": 3, "kerf_mm": 1,
        "parts": [{"part_id": "plate", "shape_type": "rectangle", "width_mm": 20, "height_mm": 10, "quantity": 2}]},
        "search_iterations": 0}
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert response.status_code == 200, response.text
    return request, response.json()


def test_confirmation_uses_exact_reviewed_plan_once_without_renesting(client, monkeypatch):
    request, result = planned(client)
    assert result["plan_id"] == "plan-001"
    monkeypatch.setattr(HoleAwareNester, "nest_batch_across_sheets",
                        lambda *a, **k: pytest.fail("Confirmation/retry must not replan"))
    assert client.post("/api/v1/execute-pipeline", json=request).json() == result
    assert client.post("/api/v1/verified-plans/plan-001/confirm", json={}).status_code == 422
    accepted = client.post("/api/v1/verified-plans/plan-001/confirm", json={"operator_confirmed": True})
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()
    assert receipt["gcode_programs"] == result["gcode_programs"]
    assert receipt["nesting"] == result["nesting"]
    assert receipt["committed_remnants"][0]["location"] == "Rack A"
    remaining = client.app.state.db.get_remnant("RX-PLAN").polygon.wkt
    assert client.post("/api/v1/verified-plans/plan-001/confirm", json={"operator_confirmed": True}).json() == receipt
    assert client.app.state.db.get_remnant("RX-PLAN").polygon.wkt == remaining


def test_stale_reviewed_plan_cannot_modify_any_sheet_or_create_receipt(client):
    db = client.app.state.db
    originals = {sid: db.upsert_remnant(sid, "steel", 3, box(0, 0, 100, 100)) for sid in ["A", "B"]}
    result = {"nesting": {"total_placed": 2, "total_requested": 2},
              "gcode_programs": [{"verification": {"verified_safe": True}}]}
    save_plan(db, "stale-plan", "hash", result, {"A": [box(10, 10, 20, 20)], "B": [box(10, 10, 20, 20)]},
              1, {sid: rec.polygon.wkt for sid, rec in originals.items()},
              {sid: ("steel", 3, "supplied") for sid in originals})
    db.upsert_remnant("B", "ss304", 3, box(0, 0, 100, 100))
    with pytest.raises(ValueError, match="STALE"):
        confirm_plan(db, "stale-plan")
    assert db.get_remnant("A").polygon.equals(originals["A"].polygon)
    with db._connect() as conn:
        assert conn.execute("SELECT receipt FROM verified_plans WHERE plan_id='stale-plan'").fetchone()[0] is None


def test_location_changes_do_not_relabel_material_or_geometry(client):
    _, result = planned(client)
    response = client.post("/api/v1/remnants/RX-PLAN/location", json={"location": "  Rack C / 2  "})
    assert response.status_code == 200
    stock = response.json()
    assert stock["location"] == "Rack C / 2"
    assert stock["geometry"] == result["candidate_sheets"][0]["geometry"]
    assert stock["material"] == "steel"


def test_duplicate_photo_with_new_physical_id_is_blocked_before_inference(client, monkeypatch):
    payload, _ = scan(client)
    monkeypatch.setattr(RemnantOpticalIndexer, "fetch_sam3_mask", lambda *a, **k: pytest.fail("Duplicate must not call SAM"))
    response = client.post("/api/v1/index-remnant", json={**payload, "review_id": "another-review", "sheet_id": "RX-002"})
    assert response.status_code == 422 and "DUPLICATE_CAPTURE" in response.text and "RX-001" in response.text


def test_recovered_plan_identifies_changed_stock(client):
    _, result = planned(client)
    client.app.state.db.upsert_remnant("RX-PLAN", "steel", 3, box(0, 0, 100, 100))
    recovered = client.get("/api/v1/verified-plans/plan-001").json()
    assert recovered["stale_inventory"] == ["RX-PLAN"]
    assert recovered["gcode_programs"] == result["gcode_programs"]
