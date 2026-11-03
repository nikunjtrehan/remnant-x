"""Isolated reproductions from the code audit; never use live inventory or models."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from shapely import affinity
from shapely.geometry import box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator as Orders
from backend.order_intent import check_order_intent, inspect_order_prompt
from backend.pipeline import execute_pipeline
from backend.schemas import FullPipelineRequest


def order():
    return {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1,
            "parts": [{"part_id": "DISC", "shape_type": "circle", "quantity": 1, "diameter_mm": 20}]}


@pytest.mark.parametrize("field,bad", [("thickness_mm", None), ("thickness_mm", True),
                                        ("kerf_mm", {}), ("diameter_mm", []),
                                        ("diameter_mm", True), ("quantity", 10**400)],
                         ids=["null-thickness", "boolean-thickness", "object-kerf", "array-diameter", "boolean-diameter", "overflow-quantity"])
def test_invalid_numeric_values_raise_validation_errors_instead_of_server_errors(field, bad):
    payload = order()
    target = payload if field in {"thickness_mm", "kerf_mm"} else payload["parts"][0]
    target[field] = bad
    with pytest.raises(ValueError, match="ERR_"):
        Orders.validate_and_parse_order_dict(payload)


def test_unused_null_dimensions_do_not_break_an_otherwise_valid_circle():
    payload = order()
    payload["parts"][0].update(width_mm=None, height_mm=None, inner_diam_mm=None)
    spec = Orders.validate_and_parse_order_dict(payload)
    assert spec.parts[0].diameter_mm == 20
    assert payload["parts"][0]["width_mm"] is None  # Caller input remains unchanged.


def test_l_bracket_dimensions_cannot_be_silently_mirrored():
    payload = {"material": "ss304", "thickness_mm": 3, "kerf_mm": 1, "parts": [
        {"part_id": "L", "shape_type": "l_bracket", "quantity": 1,
         "width_mm": 60, "height_mm": 40, "thickness_leg_mm": 10}]}
    expected = Orders.validate_and_parse_order_dict(payload)
    swapped = deepcopy(payload)
    swapped["parts"][0].update(width_mm=40, height_mm=60)
    other = Orders.validate_and_parse_order_dict(swapped)
    a = Orders.build_cad_part_specs(expected)[0].polygon
    b = Orders.build_cad_part_specs(other)[0].polygon
    assert not any(CADPartFactory.normalize_to_origin(affinity.rotate(a, angle)).equals(b)
                   for angle in (0, 90, 180, 270))
    intent = inspect_order_prompt("Cut 1 L-bracket 60 x 40 mm, leg width 10 mm, from 3 mm ss304 sheet, kerf 1 mm.")
    check_order_intent(intent, expected)
    with pytest.raises(ValueError, match="ERR_ORDER_NEEDS_CLARIFICATION"):
        check_order_intent(intent, other)


@pytest.mark.parametrize("changed_request", [False, True])
def test_concurrent_retries_recover_one_canonical_plan_without_changing_stock(tmp_path, monkeypatch, changed_request):
    import backend.pipeline as pipeline

    app = create_app(str(tmp_path / "warehouse.sqlite"), str(tmp_path / "artifacts"))
    db = app.state.db
    original = box(0, 0, 100, 100)
    db.upsert_remnant("STOCK", "ss304", 3, original)
    barrier = threading.Barrier(2)
    original_get = pipeline.get_plan
    def simultaneous_cache_miss(*args, **kwargs):
        cached = original_get(*args, **kwargs)
        barrier.wait(timeout=15)
        return cached
    monkeypatch.setattr(pipeline, "get_plan", simultaneous_cache_miss)
    req = FullPipelineRequest(order=order(), plan_id="audit-concurrent-plan", search_iterations=0)
    def run(index):
        request = req.model_copy(deep=True)
        if changed_request and index:
            request.order["parts"][0]["quantity"] = 2
        try:
            return execute_pipeline(request, db, app.state.llm, tmp_path / "artifacts" / "uploads")
        except ValueError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    if changed_request:
        assert sum(isinstance(r, dict) for r in results) == 1
        error, = [r for r in results if isinstance(r, ValueError)]
        assert "ERR_PLAN_INPUT_CHANGED" in str(error)
    else:
        assert results[0] == results[1]
        assert results[0]["nesting"]["total_placed"] == 1
    assert db.get_remnant("STOCK").polygon.equals(original)
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verified_plans").fetchone()[0] == 1


@pytest.mark.parametrize("reviewed", [False, True])
def test_fully_consumed_stock_is_excluded_from_available_inventory(tmp_path, reviewed):
    from fastapi.testclient import TestClient

    app = create_app(str(tmp_path / "warehouse.sqlite"), str(tmp_path / "artifacts"))
    app.state.db.upsert_remnant("FULL", "ss304", 3, box(0, 0, 100, 100))
    client = TestClient(app, raise_server_exceptions=False)
    request = {"order": {"material": "ss304", "thickness_mm": 3, "kerf_mm": 0,
                          "parts": [{"shape_type": "rectangle", "quantity": 1, "width_mm": 100, "height_mm": 100}]},
               "search_iterations": 0, "commit_cuts_to_db": not reviewed}
    if reviewed:
        request["plan_id"] = "audit-fully-consumed"
    response = client.post("/api/v1/execute-pipeline", json=request)
    assert response.status_code == 200, response.text
    if reviewed:
        response = client.post("/api/v1/verified-plans/audit-fully-consumed/confirm", json={"operator_confirmed": True})
    assert response.status_code == 200, response.text
    assert response.json()["committed_remnants"][0]["usable_area_mm2"] == 0
    assert app.state.db.get_remnant("FULL").usable_area_mm2 == 0  # Historical record is kept.
    assert client.get("/api/v1/remnants").json()["count"] == 0
    assert client.get("/api/v1/remnants?material=ss304&thickness_mm=3").json()["count"] == 0


def test_single_sheet_cut_helper_keeps_receipt_but_not_available_stock(tmp_path):
    from backend.db_and_parts import RemnantWarehouseDB

    db = RemnantWarehouseDB(str(tmp_path / "warehouse.sqlite"))
    sheet = box(0, 0, 10, 10)
    db.upsert_remnant("FULL", "ss304", 3, sheet)
    assert db.commit_cut_to_sheet("FULL", [sheet]).usable_area_mm2 == 0
    assert db.get_remnant("FULL") is not None
    assert db.query_compatible_remnants("ss304", 3, min_usable_area_mm2=0) == []


@pytest.mark.parametrize("part", [
    {"shape_type": "circle", "diameter_mm": 0.0001},
    {"shape_type": "ring", "outer_diam_mm": 20, "inner_diam_mm": 0.0001},
], ids=["collapsed-outer", "collapsed-hole"])
def test_output_precision_cannot_verify_a_collapsed_cut_contour(tmp_path, part):
    from fastapi.testclient import TestClient

    app = create_app(str(tmp_path / "warehouse.sqlite"), str(tmp_path / "artifacts"))
    sheet = box(0, 0, 100, 100)
    app.state.db.upsert_remnant("STOCK", "ss304", 3, sheet)
    payload = order()
    payload["kerf_mm"] = 0
    payload["parts"] = [{**part, "quantity": 1}]
    response = TestClient(app).post("/api/v1/execute-pipeline", json={
        "order": payload, "search_iterations": 0, "plan_id": "audit-collapsed-contour"})
    assert response.status_code == 422, response.text[:250]
    assert app.state.db.get_remnant("STOCK").polygon.equals(sheet)
    with app.state.db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM verified_plans").fetchone()[0] == 0


def test_inventory_thickness_filter_uses_the_same_tolerance_with_and_without_material(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(str(tmp_path / "warehouse.sqlite"), str(tmp_path / "artifacts"))
    app.state.db.upsert_remnant("STOCK", "ss304", 3, box(0, 0, 100, 100))
    client = TestClient(app)
    a = client.get("/api/v1/remnants?thickness_mm=3.005").json()
    b = client.get("/api/v1/remnants?material=ss304&thickness_mm=3.005").json()
    assert a["count"] == b["count"] == 1


def test_dxf_stock_context_rejects_kerf_outside_the_supported_order_range():
    from backend.schemas import OrderStockContext

    assert OrderStockContext(material="ss304", thickness_mm=3, kerf_mm=15).kerf_mm == 15
    with pytest.raises(ValueError):
        OrderStockContext(material="ss304", thickness_mm=3, kerf_mm=16)


@pytest.mark.parametrize("changed_request", [False, True])
def test_review_save_retry_is_idempotent_without_accepting_changed_inputs(tmp_path, changed_request):
    from backend.db_and_parts import RemnantWarehouseDB
    from backend.review_workflow import save_review

    db = RemnantWarehouseDB(str(tmp_path / "warehouse.sqlite"))
    first = save_review(db, "audit-review", "original-inputs", {"review_id": "audit-review"})
    if changed_request:
        with pytest.raises(ValueError, match="ERR_REVIEW_INPUT_CHANGED"):
            save_review(db, "audit-review", "changed-inputs", {"review_id": "audit-review"})
    else:
        assert save_review(db, "audit-review", "original-inputs", {"review_id": "audit-review"}) == first


def test_competing_reviews_cannot_save_the_same_photo_as_two_stock_items(tmp_path):
    from backend.db_and_parts import RemnantWarehouseDB
    from backend.review_workflow import save_review, accept_review
    from backend.serialization import polygon_to_dict

    db = RemnantWarehouseDB(str(tmp_path / "warehouse.sqlite"))
    result = {"photo_sha256": "a" * 64, "geometry": polygon_to_dict(box(0, 0, 100, 100)),
              "outer_area_mm2": 10000, "usable_area_mm2": 10000, "dxf_path": "", "inventory_source": "sam",
              "review_fields": {"sheet_id": "STOCK_A", "material": "ss304", "thickness_mm": 3, "location": ""}}
    save_review(db, "audit-review-a", "inputs-a", result)
    # Both requests may have passed the HTTP pre-check before either saved.
    other = deepcopy(result)
    other["review_fields"]["sheet_id"] = "STOCK_B"
    with pytest.raises(ValueError, match="ERR_DUPLICATE_CAPTURE"):
        save_review(db, "audit-review-b", "inputs-b", other)
    accept_review(db, "audit-review-a")
    assert [s.sheet_id for s in db.query_compatible_remnants("ss304", 3)] == ["STOCK_A"]


def test_concurrent_accept_and_reject_across_workers_cannot_leave_accepted_stock_marked_rejected(tmp_path, monkeypatch):
    from concurrent.futures import TimeoutError
    from backend.db_and_parts import RemnantWarehouseDB
    from backend.review_workflow import save_review, accept_review, reject_review, get_review
    from backend.serialization import polygon_to_dict

    db = RemnantWarehouseDB(str(tmp_path / "warehouse.sqlite"))
    # Independent handles represent separate API workers sharing one warehouse.
    accepting_db = RemnantWarehouseDB(db.db_path)
    result = {"geometry": polygon_to_dict(box(0, 0, 100, 100)), "outer_area_mm2": 10000,
              "usable_area_mm2": 10000, "dxf_path": "", "inventory_source": "sam",
              "review_fields": {"sheet_id": "STOCK_A", "material": "ss304", "thickness_mm": 3, "location": ""}}
    save_review(db, "audit-review", "inputs", result)
    original_connect = db._connect
    accepting = []

    def attempt(action):
        try:
            action(accepting_db if action is accept_review else db, "audit-review")
            return "ok"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=1) as workers:
        class Connection:
            def __init__(self):
                self.context = original_connect()

            def __enter__(self):
                self.connection = self.context.__enter__()
                return self

            def __exit__(self, *args):
                return self.context.__exit__(*args)

            def execute(self, sql, parameters=()):
                cursor = self.connection.execute(sql, parameters)
                if sql.startswith("SELECT accepted FROM intake_reviews"):
                    row = cursor.fetchone()
                    accepting.append(workers.submit(attempt, accept_review))
                    # Let acceptance commit between rejection's read and write
                    # if no transaction protects that interval.
                    try:
                        accepting[0].result(timeout=1)
                    except TimeoutError:
                        pass
                    class Cursor:
                        def fetchone(self):
                            return row
                    return Cursor()
                return cursor

        monkeypatch.setattr(db, "_connect", Connection)
        outcomes = [attempt(reject_review), accepting[0].result(timeout=5)]
    assert outcomes.count("ok") == 1
    status = get_review(db, "audit-review")["review_status"]
    assert (db.get_remnant("STOCK_A") is not None) == (status == "accepted")
