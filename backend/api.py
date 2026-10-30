"""HTTP routes for inventory, optical indexing, DXF uploads and batch execution.

The manufacturing workflow lives in pipeline.py; schemas and serialization are
shared explicitly so the UI contract stays independent of workflow internals.
"""

from __future__ import annotations

import os
import base64
import hashlib
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from cv2 import error as cv2_error, imencode
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, RemnantWarehouseDB
from backend.llm_client import LiveModelClient
from backend.materials import normalize_material
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.pipeline import checked_uploads, check_order_uploads, execute_pipeline
from backend.photo_preflight import decode_station_image, photo_preflight
# Request types and serializers remain importable here for earlier Python callers.
from backend.schemas import (
    FullPipelineRequest, IndexImageRequest, NaturalLanguageOrderRequest,
    RequestModel, StationImageRequest, StructuredOrderRequest, UpsertRemnantRequest,
    StockLocationRequest, ConfirmCutRequest,
)
from backend.review_workflow import (
    accept_review, cached_review, confirm_plan, get_plan, get_review,
    pending_reviews, reject_review, save_review,
)
from backend.serialization import (
    dict_to_polygon, polygon_to_dict, serialize_compiled_gcode,
    serialize_placed_part, serialize_remnant, serialize_sheet_outcome,
)


# ==========================================================
# FastAPI App Factory & State
# ==========================================================
def create_app(db_path: Optional[str] = None, artifact_dir: Optional[str] = None) -> FastAPI:
    resolved_db_path = db_path or os.getenv("REMNANTX_DB_PATH", "warehouse.db")
    app = FastAPI(
        title="RemnantX Industrial Spatial AI Backend",
        version="1.0.0",
        description="ArUco/SAM remnant indexing, Muse Spark order parsing, parallel NFP/annealing nesting and verified controller output",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Importing the ASGI module does not create or modify an inventory database.
    class LazyWarehouse:
        instance = None
        lock = threading.Lock()
        def __getattr__(self, name):
            with self.lock:
                if self.instance is None:
                    self.instance = RemnantWarehouseDB(resolved_db_path)
            return getattr(self.instance, name)
    db = LazyWarehouse()
    artifact_root = Path(artifact_dir or os.getenv("REMNANTX_ARTIFACT_DIR", "artifacts")).resolve()
    upload_root = artifact_root / "uploads"


    @app.post("/api/v1/upload-dxf")
    async def upload_dxf(file: UploadFile = File(...)):
        if not (file.filename or "").lower().endswith(".dxf"):
            raise HTTPException(422, "ERR_DXF_EXTENSION")
        data = await file.read(5_000_001)
        await file.close()
        if not data or len(data) > 5_000_000:
            raise HTTPException(422, "ERR_DXF_SIZE: limit is 5 MB")
        upload_root.mkdir(parents=True, exist_ok=True)
        target = upload_root / (uuid.uuid4().hex + ".dxf")
        try:
            target.write_bytes(data)
            import_info = {}
            poly = CADPartFactory.load_part_from_dxf(str(target), import_info)
            # Managed uploads are canonical mm polylines; downstream stages use
            # exactly the reviewed approximation rather than flattening again.
            CADPartFactory.save_part_to_dxf(poly, str(target))
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(422, "ERR_INVALID_VENDOR_DXF: " + str(exc))
        return {"status": "UPLOADED", "filename": file.filename, "dxf_path": str(target),
                "geometry": polygon_to_dict(poly), "units": "mm", "hole_count": len(poly.interiors), "import_info": import_info}
    llm = LiveModelClient()
    app.state.db = db
    app.state.llm = llm

    @app.post("/api/v1/photo-preflight")
    def check_station_photo(req: StationImageRequest) -> Dict[str, Any]:
        """Check markers and calibration without SAM, files or warehouse writes."""
        try:
            return photo_preflight(req, llm)
        except (ValueError, cv2_error) as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/v1/artifacts/{filename}")
    def download_indexed_dxf(filename: str):
        target = (artifact_root / filename).resolve()
        if (target.parent != artifact_root or target.suffix.lower() != ".dxf"
                or not target.is_file()):
            raise HTTPException(404, "ERR_ARTIFACT_NOT_FOUND")
        return FileResponse(target, media_type="application/dxf", filename=target.name)

    @app.get("/api/v1/health")
    def health_check() -> Dict[str, Any]:
        return {
            "status": "ok",
            "service": "RemnantX Backend",
            "providers": {
                "primary_order_provider": llm.order_provider,
                "baseten_configured": llm.has_baseten,
                "baseten_model": llm.baseten_model,
                "meta_configured": llm.has_meta,
                "meta_spark_model": llm.meta_spark_model,
                "sam_model": "sam-3.1",
                "fireworks_configured": llm.has_fireworks,
            },
        }

    @app.get("/api/v1/remnants")
    def list_remnants(
        material: Optional[str] = None,
        thickness_mm: Optional[float] = None,
        min_usable_area_mm2: float = 0.0,
    ) -> Dict[str, Any]:
        if material and thickness_mm is not None:
            records = db.query_compatible_remnants(
                material=material,
                thickness_mm=thickness_mm,
                min_usable_area_mm2=min_usable_area_mm2,
            )
        else:
            # Query common shop combinations or direct SQLite table scan
            with db._connect() as conn:
                rows = conn.execute(
                    "SELECT sheet_id FROM remnants ORDER BY usable_area_mm2 ASC"
                ).fetchall()
            records = []
            for (sid,) in rows:
                r = db.get_remnant(sid)
                if r is not None:
                    if material and r.material != normalize_material(material):
                        continue
                    if (
                        thickness_mm is not None
                        and abs(r.thickness_mm - thickness_mm) > 1e-3
                    ):
                        continue
                    if r.usable_area_mm2 >= min_usable_area_mm2:
                        records.append(r)

        return {
            "count": len(records),
            "remnants": [serialize_remnant(r) for r in records],
        }

    @app.post("/api/v1/remnants")
    def upsert_remnant_endpoint(req: UpsertRemnantRequest) -> Dict[str, Any]:
        try:
            poly = dict_to_polygon({"exterior": req.exterior, "holes": req.holes})
            rec = db.upsert_remnant(
                sheet_id=req.sheet_id,
                material=req.material,
                thickness_mm=req.thickness_mm,
                polygon=poly,
                dxf_path=req.dxf_path,
            )
            return {"status": "UPSERTED", "remnant": serialize_remnant(rec)}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/v1/seed-demo-warehouse")
    def seed_demo_warehouse() -> Dict[str, Any]:
        """Seeds the warehouse with realistic irregular & L-hole industrial remnants for instant live demos."""
        s1_poly = Polygon(
            shell=[(0, 0), (260, 0), (260, 180), (0, 180)],
            holes=[[(40, 40), (110, 40), (110, 110), (40, 110)]],
        )
        s2_poly = Polygon(
            shell=[(0, 0), (420, 0), (420, 280), (0, 280)],
            holes=[
                [
                    (60, 50),
                    (180, 50),
                    (180, 110),
                    (120, 110),
                    (120, 200),
                    (60, 200),
                ]
            ],
        )
        s3_poly = Polygon(
            shell=[(0, 0), (320, 0), (320, 220), (0, 220)],
            holes=[],
        )

        r1 = db.upsert_remnant("DEMO_STEEL_SMALL_01", "steel", 3.0, s1_poly, source="demo")
        r2 = db.upsert_remnant("DEMO_STEEL_LHOLE_02", "steel", 3.0, s2_poly, source="demo")
        r3 = db.upsert_remnant("DEMO_ALUM_CLEAN_03", "aluminum", 2.0, s3_poly, source="demo")

        return {
            "status": "SEEDED",
            "seeded_count": 3,
            "inventory_source": "demo",
            "notice": "Synthetic demo stock. Pipeline requires allow_demo_stock=true to use it. Reseeding resets these DEMO_ records.",
            "remnants": [serialize_remnant(r) for r in (r1, r2, r3)],
        }

    def index_remnant(req: IndexImageRequest) -> Dict[str, Any]:
        try:
            request_hash = hashlib.sha256(req.model_dump_json().encode()).hexdigest()
            if req.review_id:
                if req.save_to_warehouse:
                    raise ValueError("ERR_REVIEW_REQUIRED: Reviewed scans must be accepted separately.")
                previous = cached_review(db, req.review_id, request_hash)
                if previous:
                    return previous
                if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", req.sheet_id):
                    raise ValueError("ERR_STOCK_ID: Use letters, numbers, dots, hyphens or underscores for the physical stock ID.")
                if db.get_remnant(req.sheet_id):
                    raise ValueError("ERR_STOCK_ID_EXISTS: This stock ID already exists. Inspect inventory before photographing the same sheet again.")
                photo_hash = hashlib.sha256(base64.b64decode(req.image_base64.split(",")[-1], validate=True)).hexdigest()
                with db._connect() as conn:
                    duplicate = conn.execute("SELECT json_extract(payload,'$.review_fields.sheet_id') FROM intake_reviews WHERE accepted>=0 AND json_extract(payload,'$.photo_sha256')=?", (photo_hash,)).fetchone()
                if duplicate:
                    raise ValueError("ERR_DUPLICATE_CAPTURE: This exact photo already belongs to stock " + duplicate[0] + ". Recover its review or inspect inventory.")
            if not req.material.strip():
                raise ValueError("ERR_MISSING_MATERIAL: Specify the material grade and thickness from the stock label.")
            material = normalize_material(req.material)
            img_bgr = decode_station_image(req.image_base64)

            cfg = StationCalibrationConfig(
                table_width_mm=req.table_width_mm,
                table_height_mm=req.table_height_mm,
                marker_size_mm=req.marker_size_mm,
            )
            indexer = RemnantOpticalIndexer(cfg, llm_client=llm)
            dxf_out = str(artifact_root / (uuid.uuid4().hex + ".dxf"))
            res = indexer.index_remnant_from_image(
                img_bgr=img_bgr,
                dxf_out_path=dxf_out,
                use_live_vision_audit=req.use_live_vision_audit,
                segmentation_mode=req.segmentation_mode, concept=req.segmentation_concept,
                object_id=req.segmentation_object_id, use_clahe=req.use_clahe,
                box_prompt=req.segmentation_box_px,
            )

            poly = Polygon(
                shell=res.outer_polygon_mm, holes=res.interior_holes_mm
            )
            saved_rec = None
            if req.save_to_warehouse:
                saved_rec = db.upsert_remnant(
                    sheet_id=req.sheet_id,
                    material=req.material,
                    thickness_mm=req.thickness_mm,
                    polygon=poly,
                    dxf_path=res.dxf_path,
                    source=res.vision_audit["segmentation"]["source"],
                    location=req.location,
                )

            result = {
                "status": res.status,
                "camera_angle_deg": res.camera_angle_deg,
                "measured_marker_mm": res.measured_marker_mm,
                "scale_drift_mm": res.scale_drift_mm,
                "outer_area_mm2": res.outer_area_mm2,
                "usable_area_mm2": res.usable_area_mm2,
                "hole_count": res.hole_count,
                "geometry": polygon_to_dict(poly),
                "dxf_path": res.dxf_path,
                "vision_audit": res.vision_audit,
                "timings_ms": res.timings_ms,
                "saved_remnant": serialize_remnant(saved_rec) if saved_rec else None,
            }
            if req.review_id:
                # Same calibrated station frame, without another model request.
                cal = indexer.calibrate_and_flatten(img_bgr)
                ok, preview = imencode(".jpg", cal.warped_bgr)
                if not ok:
                    raise ValueError("ERR_PREVIEW_ENCODING")
                result.update({
                    "review_id": req.review_id,
                    "photo_sha256": photo_hash,
                    "inventory_source": res.vision_audit["segmentation"]["source"],
                    "review_fields": {"sheet_id": req.sheet_id, "material": material,
                                      "thickness_mm": req.thickness_mm, "location": req.location.strip()},
                    "review_image_base64": "data:image/jpeg;base64," + base64.b64encode(preview).decode(),
                    "review_frame": {"width_mm": req.table_width_mm, "height_mm": req.table_height_mm},
                    "review_blocked": (poly.bounds[0] <= 1 or poly.bounds[1] <= 1
                                       or poly.bounds[2] >= req.table_width_mm - 1
                                       or poly.bounds[3] >= req.table_height_mm - 1),
                })
                return save_review(db, req.review_id, request_hash, result)
            return result
        except ValueError as ve:
            raise HTTPException(status_code=422, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    # A retry arriving during a reviewed scan waits for its durable result instead
    # of starting a second paid inference. No background worker service is needed.
    review_lock = threading.Lock()

    @app.post("/api/v1/index-remnant")
    def index_remnant_endpoint(req: IndexImageRequest):
        with review_lock:
            return index_remnant(req)

    @app.get("/api/v1/intake-reviews")
    def list_intake_reviews():
        return {"reviews": pending_reviews(db)}

    @app.get("/api/v1/intake-reviews/{review_id}")
    def read_intake_review(review_id: str):
        try:
            return get_review(db, review_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.post("/api/v1/intake-reviews/{review_id}/accept")
    def accept_intake_review(review_id: str):
        try:
            return accept_review(db, review_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/v1/intake-reviews/{review_id}/reject")
    def reject_intake_review(review_id: str):
        try:
            return reject_review(db, review_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/v1/remnants/{sheet_id}/location")
    def update_stock_location(sheet_id: str, req: StockLocationRequest):
        with db._connect() as conn:
            if not conn.execute("SELECT 1 FROM remnants WHERE sheet_id=?", (sheet_id,)).fetchone():
                raise HTTPException(404, "ERR_SHEET_NOT_FOUND")
            conn.execute("UPDATE remnants SET location=? WHERE sheet_id=?", (req.location.strip(), sheet_id))
        return serialize_remnant(db.get_remnant(sheet_id))

    @app.get("/api/v1/verified-plans/{plan_id}")
    def read_verified_plan(plan_id: str):
        result = get_plan(db, plan_id)
        if result is None:
            raise HTTPException(404, "ERR_PLAN_NOT_FOUND")
        return result

    @app.post("/api/v1/verified-plans/{plan_id}/confirm")
    def confirm_verified_plan(plan_id: str, req: ConfirmCutRequest):
        try:
            return confirm_plan(db, plan_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/v1/parse-order")
    def parse_natural_language_order(req: NaturalLanguageOrderRequest) -> Dict[str, Any]:
        orch = SparkWarehouseOrchestrator(db, llm_client=llm)
        try:
            prompt = req.prompt
            if req.stock:
                prompt += (f"\nUse {req.stock.thickness_mm} mm {req.stock.material} sheet. "
                           f"Kerf {req.stock.kerf_mm} mm.")
            spec = orch.parse_natural_language_order_via_spark(prompt, checked_uploads(req.uploaded_dxf_files, upload_root))
            check_order_uploads(spec, upload_root)
            return {
                "status": "PARSED_OK",
                "order": {
                    "order_id": spec.order_id,
                    "material": spec.material,
                    "thickness_mm": spec.thickness_mm,
                    "kerf_mm": spec.kerf_mm,
                    "parts": [
                        {
                            "part_id": p.part_id,
                            "shape_type": p.shape_type,
                            "quantity": p.quantity,
                            "grain_locked": p.grain_locked,
                            "diameter_mm": p.diameter_mm,
                            "outer_diam_mm": p.outer_diam_mm,
                            "inner_diam_mm": p.inner_diam_mm,
                            "width_mm": p.width_mm,
                            "height_mm": p.height_mm,
                            "thickness_leg_mm": p.thickness_leg_mm,
                            "dxf_path": p.dxf_path,
                        }
                        for p in spec.parts
                    ],
                },
                "llm_trace": orch.last_llm_trace,
            }
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    plan_lock = threading.Lock()

    @app.post("/api/v1/execute-pipeline")
    def execute_full_manufacturing_pipeline(req: FullPipelineRequest) -> Dict[str, Any]:
        """Preview a complete batch, or atomically commit it after verification."""
        try:
            with plan_lock:
                return execute_pipeline(req, db, llm, upload_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app


app = create_app()
