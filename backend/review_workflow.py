"""Durable optical reviews and exact verified plans, using the existing SQLite DB."""
import json
from datetime import datetime, timezone
from shapely import wkt
from backend.serialization import dict_to_polygon, serialize_remnant


def get_review(db, review_id):
    with db._connect() as conn:
        row = conn.execute("SELECT payload, accepted FROM intake_reviews WHERE review_id=?", (review_id,)).fetchone()
    if row is None:
        raise ValueError("ERR_REVIEW_NOT_FOUND: No completed analysis exists for this photo yet.")
    result = json.loads(row[0])
    result["review_status"] = {0: "pending", 1: "accepted", -1: "rejected"}[row[1]]
    return result


def cached_review(db, review_id, request_hash):
    with db._connect() as conn:
        row = conn.execute("SELECT request_hash FROM intake_reviews WHERE review_id=?", (review_id,)).fetchone()
    if row is None:
        return None
    if row[0] != request_hash:
        raise ValueError("ERR_REVIEW_INPUT_CHANGED: Recover or reject the earlier analysis before changing this photo's inputs.")
    return get_review(db, review_id)


def save_review(db, review_id, request_hash, result):
    payload = json.dumps(result, allow_nan=False)
    with db._connect() as conn:
        conn.execute("INSERT INTO intake_reviews(review_id,request_hash,payload) VALUES(?,?,?)", (review_id, request_hash, payload))
    return get_review(db, review_id)


def pending_reviews(db):
    with db._connect() as conn:
        rows = conn.execute("SELECT review_id,json_extract(payload,'$.review_fields') FROM intake_reviews WHERE accepted=0 ORDER BY rowid DESC").fetchall()
    return [{"review_id": rid, "fields": json.loads(fields)} for rid, fields in rows]


def accept_review(db, review_id):
    with db._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload, accepted FROM intake_reviews WHERE review_id=?", (review_id,)).fetchone()
        if row is None:
            raise ValueError("ERR_REVIEW_NOT_FOUND")
        result = json.loads(row[0])
        if row[1] == 1:
            return result
        if row[1] == -1:
            raise ValueError("ERR_REVIEW_REJECTED: Replace or reanalyze the photo.")
        if result.get("review_blocked"):
            raise ValueError("ERR_CAPTURE_TRUNCATED: The outline reaches the station edge. Recapture the whole sheet inside the station.")
        f = result["review_fields"]
        if conn.execute("SELECT 1 FROM remnants WHERE sheet_id=?", (f["sheet_id"],)).fetchone():
            raise ValueError("ERR_STOCK_ID_EXISTS: This physical stock ID is already in inventory. Check the existing sheet; do not relabel the same sheet as new stock.")
        poly = dict_to_polygon(result["geometry"])
        conn.execute("""INSERT INTO remnants
            (sheet_id,material,thickness_mm,outer_area_mm2,usable_area_mm2,hole_count,polygon_wkt,dxf_path,source,location)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (f["sheet_id"], f["material"], f["thickness_mm"], result["outer_area_mm2"],
             result["usable_area_mm2"], len(poly.interiors), poly.wkt, result["dxf_path"],
             result["inventory_source"], f["location"]))
        result["saved_remnant"] = {
            "sheet_id": f["sheet_id"], "material": f["material"], "thickness_mm": f["thickness_mm"],
            "location": f["location"], "outer_area_mm2": result["outer_area_mm2"],
            "usable_area_mm2": result["usable_area_mm2"], "hole_count": len(poly.interiors),
            "geometry": result["geometry"], "dxf_path": result["dxf_path"],
            "inventory_source": result["inventory_source"],
        }
        result["review_status"] = "accepted"
        conn.execute("UPDATE intake_reviews SET accepted=1,payload=? WHERE review_id=?",
                     (json.dumps(result, allow_nan=False), review_id))
    return result


def reject_review(db, review_id):
    with db._connect() as conn:
        row = conn.execute("SELECT accepted FROM intake_reviews WHERE review_id=?", (review_id,)).fetchone()
        if row is None:
            raise ValueError("ERR_REVIEW_NOT_FOUND")
        if row[0] == 1:
            raise ValueError("ERR_REVIEW_ALREADY_ACCEPTED: Inspect inventory; this review cannot remove an accepted sheet.")
        conn.execute("UPDATE intake_reviews SET accepted=-1 WHERE review_id=?", (review_id,))
    return {"status": "rejected"}


def get_plan(db, plan_id, request_hash=None):
    with db._connect() as conn:
        row = conn.execute("SELECT payload,receipt FROM verified_plans WHERE plan_id=?", (plan_id,)).fetchone()
    if row is None:
        return None
    payload = json.loads(row[0])
    if request_hash is not None and payload["request_hash"] != request_hash:
        raise ValueError("ERR_PLAN_INPUT_CHANGED: Review a new plan after changing the job.")
    if row[1]:
        return json.loads(row[1])
    result = payload["result"]
    stale = []
    for sid, expected in payload["expected_wkts"].items():
        current = db.get_remnant(sid)
        if (current is None or current.polygon.wkt != expected
                or (current.material, current.thickness_mm, current.source) != tuple(payload["expected_inventory"][sid])):
            stale.append(sid)
    if stale:
        result["stale_inventory"] = stale
    return result


def save_plan(db, plan_id, request_hash, result, cuts, kerf, expected_wkts, expected_inventory):
    payload = {"request_hash": request_hash, "result": result, "kerf_mm": kerf,
               "cuts": {sid: [p.wkt for p in parts] for sid, parts in cuts.items()},
               "expected_wkts": expected_wkts, "expected_inventory": expected_inventory}
    with db._connect() as conn:
        conn.execute("INSERT INTO verified_plans(plan_id,payload) VALUES(?,?)",
                     (plan_id, json.dumps(payload, allow_nan=False)))


def confirm_plan(db, plan_id):
    with db._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload,receipt FROM verified_plans WHERE plan_id=?", (plan_id,)).fetchone()
        if row is None:
            raise ValueError("ERR_PLAN_NOT_FOUND: Generate and review a plan first.")
        if row[1]:
            return json.loads(row[1])
        payload = json.loads(row[0])
        result = payload["result"]
        if (result["nesting"]["total_placed"] != result["nesting"]["total_requested"]
                or not result["gcode_programs"]
                or not all(p["verification"]["verified_safe"] for p in result["gcode_programs"])):
            raise ValueError("ERR_UNSAFE_GCODE: Only a complete verified plan may update stock.")
        records = db._apply_cuts(conn,
            {sid: [wkt.loads(p) for p in parts] for sid, parts in payload["cuts"].items()},
            payload["kerf_mm"], payload["expected_wkts"],
            {sid: tuple(meta) for sid, meta in payload["expected_inventory"].items()})
        result["committed_remnants"] = [serialize_remnant(r) for r in records]
        result["operator_confirmed_at"] = datetime.now(timezone.utc).isoformat()
        result["stock_update_basis"] = "operator_reported_cut_complete"
        # Geometry updates and the replay receipt commit together, or both roll back.
        conn.execute("UPDATE verified_plans SET receipt=? WHERE plan_id=?",
                     (json.dumps(result, allow_nan=False), plan_id))
    return result
