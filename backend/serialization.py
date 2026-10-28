"""Geometry and result serialization shared by API routes and the order pipeline."""
import math
from typing import Any, Dict, List, Optional
from shapely.geometry import Polygon
from backend.db_and_parts import RemnantRecord
from backend.materials import material_identity
from backend.m3_nfp_nester import PlacedPartInstance, SheetNestingOutcome
from backend.m4_muse_gcode import CompiledSheetGCode

def polygon_to_dict(poly: Optional[Polygon]) -> Optional[Dict[str, Any]]:
    if poly is None or poly.is_empty:
        return None
    if poly.geom_type == "MultiPolygon":
        return {"type": "MultiPolygon", "polygons": [polygon_to_dict(g) for g in poly.geoms], "area_mm2": float(poly.area)}
    exterior = [
        [round(float(x), 2), round(float(y), 2)] for x, y in poly.exterior.coords
    ]
    holes = [
        [[round(float(x), 2), round(float(y), 2)] for x, y in ring.coords]
        for ring in poly.interiors
    ]
    minx, miny, maxx, maxy = poly.bounds
    return {
        "exterior": exterior,
        "holes": holes,
        "bounds": [
            round(float(minx), 2),
            round(float(miny), 2),
            round(float(maxx), 2),
            round(float(maxy), 2),
        ],
        "area_mm2": round(float(poly.area), 2),
    }

def dict_to_polygon(data: Dict[str, Any]) -> Polygon:
    exterior = [(float(pt[0]), float(pt[1])) for pt in data.get("exterior", [])]
    holes = [
        [(float(pt[0]), float(pt[1])) for pt in ring]
        for ring in data.get("holes", [])
    ]
    poly = Polygon(shell=exterior, holes=holes)
    if poly.is_empty or not poly.is_valid or any(not math.isfinite(v) for pt in exterior for v in pt):
        raise ValueError("ERR_INVALID_POLYGON")
    return poly

def serialize_remnant(rec: RemnantRecord) -> Dict[str, Any]:
    return {
        "sheet_id": rec.sheet_id,
        "material": rec.material,
        **material_identity(rec.material),
        "inventory_source": rec.source,
        "thickness_mm": rec.thickness_mm,
        "outer_area_mm2": rec.outer_area_mm2,
        "usable_area_mm2": rec.usable_area_mm2,
        "hole_count": rec.hole_count,
        "dxf_path": rec.dxf_path,
        "geometry": polygon_to_dict(rec.polygon),
    }

def serialize_placed_part(p: PlacedPartInstance) -> Dict[str, Any]:
    return {
        "instance_id": p.instance_id,
        "part_id": p.part_id,
        "name": p.name,
        "sheet_id": p.sheet_id,
        "x_mm": round(float(p.x_mm), 2),
        "y_mm": round(float(p.y_mm), 2),
        "rotation_deg": round(float(p.rotation_deg), 2),
        "geometry": polygon_to_dict(p.polygon),
    }

def serialize_sheet_outcome(out: SheetNestingOutcome) -> Dict[str, Any]:
    return {
        "sheet_id": out.sheet_id,
        "outer_area_mm2": out.outer_area_mm2,
        "initial_usable_area_mm2": out.initial_usable_area_mm2,
        "remaining_usable_area_mm2": out.remaining_usable_area_mm2,
        "utilization_pct": out.utilization_pct,
        "placed_parts": [serialize_placed_part(p) for p in out.placed_parts],
        "kerf_safe_zone": polygon_to_dict(out.kerf_safe_zone_polygon),
    }

def serialize_compiled_gcode(cg: CompiledSheetGCode) -> Dict[str, Any]:
    return {
        "sheet_id": cg.sheet_id,
        "origin_x_mm": cg.origin_x_mm,
        "origin_y_mm": cg.origin_y_mm,
        "gcode_text": cg.gcode_text,
        "ordered_loops": [
            {
                "loop_index": seg.loop_index,
                "instance_id": seg.instance_id,
                "loop_type": seg.loop_type,
                "coords_mm": [[x, y] for x, y in seg.coords_mm],
            }
            for seg in cg.ordered_loops
        ],
        "verification": {
            "verified_safe": cg.verification.verified_safe,
            "active_cut_loops_count": cg.verification.active_cut_loops_count,
            "hole_collision_length_mm": cg.verification.hole_collision_length_mm,
            "outside_sheet_length_mm": cg.verification.outside_sheet_length_mm,
            "inside_out_order_valid": cg.verification.inside_out_order_valid,
            "total_cut_distance_mm": cg.verification.total_cut_distance_mm,
            "total_rapid_distance_mm": cg.verification.total_rapid_distance_mm,
            "error_message": cg.verification.error_message,
        },
        "llm_trace": cg.llm_trace,
    }
