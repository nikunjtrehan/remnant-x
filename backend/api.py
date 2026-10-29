"""HTTP routes for inventory, optical indexing, DXF uploads and batch execution.

The manufacturing workflow lives in pipeline.py; schemas and serialization are
shared explicitly so the UI contract stays independent of workflow internals.
"""

from __future__ import annotations

import base64
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from shapely.geometry import Polygon

from backend.db_and_parts import CADPartFactory, RemnantWarehouseDB
from backend.llm_client import LiveModelClient
from backend.materials import normalize_material
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.pipeline import checked_uploads, check_order_uploads, execute_pipeline
# Request types and serializers remain importable here for earlier Python callers.
from backend.schemas import (
    FullPipelineRequest, IndexImageRequest, NaturalLanguageOrderRequest,
    RequestModel, StructuredOrderRequest, UpsertRemnantRequest,
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
            poly = CADPartFactory.load_part_from_dxf(str(target))
        except Exception as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(422, "ERR_INVALID_VENDOR_DXF: " + str(exc))
        return {"status": "UPLOADED", "filename": file.filename, "dxf_path": str(target),
                "geometry": polygon_to_dict(poly), "units": "mm", "hole_count": len(poly.interiors)}
    llm = LiveModelClient()
    app.state.db = db
    app.state.llm = llm

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

    @app.post("/api/v1/index-remnant")
    def index_remnant_endpoint(req: IndexImageRequest) -> Dict[str, Any]:
        try:
            b64_clean = req.image_base64.split(",")[-1]
            img_bytes = base64.b64decode(b64_clean, validate=True)
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                raise ValueError("ERR_DECODE_IMAGE: Could not decode base64 image.")

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
                )

            return {
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
        except ValueError as ve:
            raise HTTPException(status_code=422, detail=str(ve))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/v1/parse-order")
    def parse_natural_language_order(req: NaturalLanguageOrderRequest) -> Dict[str, Any]:
        orch = SparkWarehouseOrchestrator(db, llm_client=llm)
        try:
            spec = orch.parse_natural_language_order_via_spark(req.prompt, checked_uploads(req.uploaded_dxf_files, upload_root))
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

    @app.post("/api/v1/execute-pipeline")
    def execute_full_manufacturing_pipeline(req: FullPipelineRequest) -> Dict[str, Any]:
        """Preview a complete batch, or atomically commit it after verification."""
        try:
            return execute_pipeline(req, db, llm, upload_root)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app


app = create_app()
