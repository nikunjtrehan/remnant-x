from dataclasses import dataclass
import math
import os
import sqlite3
from typing import Dict, List, Optional, Tuple
import ezdxf
from shapely import wkt
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from backend.materials import normalize_material
from contextlib import contextmanager
import uuid
import threading


@dataclass
class RemnantRecord:
    sheet_id: str
    material: str
    thickness_mm: float
    outer_area_mm2: float
    usable_area_mm2: float
    hole_count: int
    polygon: Polygon
    dxf_path: str
    source: str = "supplied"
    location: str = ""


@dataclass
class CADPartSpec:
    part_id: str
    name: str
    polygon: Polygon  # Normalized with bottom-left at (0,0); may contain interior screw holes!
    quantity: int = 1
    grain_locked: bool = False  # If True, only [0, 180] deg rotations allowed (Scenario 5)

    @property
    def solid_area_mm2(self) -> float:
        return round(float(self.polygon.area), 2)

    @property
    def envelope_area_mm2(self) -> float:
        return round(float(Polygon(self.polygon.exterior.coords).area), 2)


class RemnantWarehouseDB:
    """Module 0A: SQLite Warehouse Inventory Manager.

    - Stores indexed scrap sheets with exact Shapely WKT geometry (outer shell + interior holes).
    - Ranks sheets Smallest-Usable-First (Scenario 6).
    - Supports 1-Click 'Commit Cut' subtraction without re-photographing (Scenario 3).
    """

    def __init__(self, db_path: str = "warehouse.db"):
        self.db_path = db_path
        self._memory = sqlite3.connect(":memory:", check_same_thread=False) if db_path == ":memory:" else None
        self._lock = threading.RLock()
        self._init_schema()

    @contextmanager
    def _connect(self):
        with self._lock:
            conn = self._memory or sqlite3.connect(self.db_path)
            try:
                with conn:
                    yield conn
            finally:
                if self._memory is None:
                    conn.close()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            # Enable Write-Ahead Logging for power-cut resilience & concurrent FastAPI reads
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS remnants (
                    sheet_id TEXT PRIMARY KEY,
                    material TEXT NOT NULL,
                    thickness_mm REAL NOT NULL,
                    outer_area_mm2 REAL NOT NULL,
                    usable_area_mm2 REAL NOT NULL,
                    hole_count INTEGER NOT NULL,
                    polygon_wkt TEXT NOT NULL,
                    dxf_path TEXT NOT NULL
                )
            """)
            # B-Tree composite index for sub-0.2ms Smallest-Remnant-First filtering
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_remnants_lookup
                ON remnants (material, thickness_mm, usable_area_mm2 ASC)
            """)
            if "source" not in {row[1] for row in conn.execute("PRAGMA table_info(remnants)")}:
                conn.execute("ALTER TABLE remnants ADD COLUMN source TEXT NOT NULL DEFAULT 'supplied'")
            if "location" not in {row[1] for row in conn.execute("PRAGMA table_info(remnants)")}:
                conn.execute("ALTER TABLE remnants ADD COLUMN location TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE TABLE IF NOT EXISTS intake_reviews (review_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, payload TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0)")
            conn.execute("CREATE TABLE IF NOT EXISTS verified_plans (plan_id TEXT PRIMARY KEY, payload TEXT NOT NULL, receipt TEXT)")
            conn.commit()

    def upsert_remnant(
        self,
        sheet_id: str,
        material: str,
        thickness_mm: float,
        polygon: Polygon,
        dxf_path: str = "",
        source: str = "supplied",
        location: str = "",
    ) -> RemnantRecord:
        if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid:
            raise ValueError("ERR_INVALID_REMNANT_POLYGON")
        if not math.isfinite(thickness_mm) or thickness_mm <= 0:
            raise ValueError("ERR_INVALID_THICKNESS")

        outer_area = round(float(Polygon(polygon.exterior.coords).area), 2)
        usable_area = round(float(polygon.area), 2)
        hole_count = len(polygon.interiors)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO remnants
                (sheet_id, material, thickness_mm, outer_area_mm2, usable_area_mm2, hole_count, polygon_wkt, dxf_path, source, location)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    sheet_id,
                    normalize_material(material),
                    float(thickness_mm),
                    outer_area,
                    usable_area,
                    hole_count,
                    polygon.wkt,
                    dxf_path,
                    source,
                    location.strip(),
                ),
            )
            conn.commit()

        return RemnantRecord(
            sheet_id=sheet_id,
            material=normalize_material(material),
            thickness_mm=float(thickness_mm),
            outer_area_mm2=outer_area,
            usable_area_mm2=usable_area,
            hole_count=hole_count,
            polygon=polygon,
            dxf_path=dxf_path,
            source=source,
            location=location.strip(),
        )

    def get_remnant(self, sheet_id: str) -> Optional[RemnantRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sheet_id, material, thickness_mm, outer_area_mm2,"
                " usable_area_mm2, hole_count, polygon_wkt, dxf_path, source, location FROM remnants"
                " WHERE sheet_id = ?",
                (sheet_id,),
            ).fetchone()
        if not row:
            return None
        return RemnantRecord(
            sheet_id=row[0],
            material=row[1],
            thickness_mm=row[2],
            outer_area_mm2=row[3],
            usable_area_mm2=row[4],
            hole_count=row[5],
            polygon=wkt.loads(row[6]),
            dxf_path=row[7],
            source=row[8],
            location=row[9],
        )

    def query_compatible_remnants(
        self,
        material: str,
        thickness_mm: float,
        min_usable_area_mm2: float = 100.0,
        thickness_tol_mm: float = 0.01,
    ) -> List[RemnantRecord]:
        """Scenario 6: Smallest-Remnant-First Ranking.

        Returns compatible sheets ordered by usable_area_mm2 ASCENDING so the shop
        consumes smaller leftover skeletons before cutting into large sheets.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT sheet_id, material, thickness_mm, outer_area_mm2, usable_area_mm2,
                       hole_count, polygon_wkt, dxf_path, source, location
                FROM remnants
                WHERE material = ?
                  AND ABS(thickness_mm - ?) <= ?
                  AND usable_area_mm2 >= ?
                ORDER BY usable_area_mm2 ASC
            """,
                (
                    normalize_material(material),
                    float(thickness_mm),
                    thickness_tol_mm,
                    min_usable_area_mm2,
                ),
            ).fetchall()

        return [
            RemnantRecord(
                sheet_id=r[0],
                material=r[1],
                thickness_mm=r[2],
                outer_area_mm2=r[3],
                usable_area_mm2=r[4],
                hole_count=r[5],
                polygon=wkt.loads(r[6]),
                dxf_path=r[7],
                source=r[8],
                location=r[9],
            )
            for r in rows
        ]

    def commit_cut_to_sheet(
        self,
        sheet_id: str,
        placed_parts: List[Polygon],
        kerf_mm: float = 0.0,
    ) -> RemnantRecord:
        """Scenario 3: 1-Click 'Commit Cut to Warehouse'.

        Permanently subtracts the newly laser-cut parts from the sheet's usable
        geometry in SQLite without requiring a new camera photograph.
        Supports Scenario 2 (Donut-Hole Reuse): only the solid cut metal is removed;
        if a hollow ring was cut, any uncut center slug remains tracked.
        """
        return self.commit_cut_batch({sheet_id: placed_parts}, kerf_mm)[0]

    def commit_cut_batch(self, cuts, kerf_mm=0.0, expected_wkts=None, expected_inventory=None):
        """All sheets and disconnected islands in one rollback-capable transaction.

        expected_wkts rejects a stale plan if another request changed inventory.
        """
        if not math.isfinite(kerf_mm) or kerf_mm < 0:
            raise ValueError("ERR_INVALID_KERF")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            return self._apply_cuts(conn, cuts, kerf_mm, expected_wkts, expected_inventory)

    def _apply_cuts(self, conn, cuts, kerf_mm, expected_wkts=None, expected_inventory=None):
        """Shared transaction body for immediate cuts and reviewed-plan confirmation."""
        results = []
        for sheet_id, parts in cuts.items():
            row = conn.execute("SELECT material, thickness_mm, polygon_wkt, dxf_path, source, location FROM remnants WHERE sheet_id=?", (sheet_id,)).fetchone()
            if row is None:
                raise ValueError("ERR_SHEET_NOT_FOUND: " + sheet_id)
            if expected_wkts is not None and row[2] != expected_wkts[sheet_id]:
                raise ValueError("ERR_STALE_WAREHOUSE: " + sheet_id)
            if expected_inventory is not None and (row[0], row[1], row[4]) != expected_inventory[sheet_id]:
                raise ValueError("ERR_STALE_WAREHOUSE_MATERIAL: " + sheet_id)
            sheet = wkt.loads(row[2])
            if any(p.is_empty or not p.is_valid or not sheet.buffer(0.002).covers(p) for p in parts):
                raise ValueError("ERR_INVALID_CUT_FOOTPRINT")
            updated = sheet.difference(unary_union([p.buffer(kerf_mm / 2) for p in parts]))
            islands = sorted(updated.geoms, key=lambda g: g.area, reverse=True) if isinstance(updated, MultiPolygon) else [updated]
            for i, poly in enumerate(islands):
                sid = sheet_id if i == 0 else sheet_id + "_island_" + uuid.uuid4().hex[:12]
                outer = float(Polygon(poly.exterior).area)
                area = float(poly.area)
                # An old DXF no longer describes the updated stock.
                conn.execute("INSERT OR REPLACE INTO remnants (sheet_id, material, thickness_mm, outer_area_mm2, usable_area_mm2, hole_count, polygon_wkt, dxf_path, source, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (sid, row[0], row[1], outer, area, len(poly.interiors), poly.wkt, "", row[4], row[5]))
                results.append(RemnantRecord(sid, row[0], row[1], outer, area, len(poly.interiors), poly, "", row[4], row[5]))
        return results


class CADPartFactory:
    """Module 0B: Parametric CAD Part Builder & .DXF Round-Trip Loader.

    Normalizes all parts so their bounding box bottom-left sits at (0.0, 0.0).
    """

    @staticmethod
    def normalize_to_origin(poly: Polygon) -> Polygon:
        minx, miny, _, _ = poly.bounds
        shell = [(x - minx, y - miny) for x, y in poly.exterior.coords]
        holes = [
            [(x - minx, y - miny) for x, y in interior.coords]
            for interior in poly.interiors
        ]
        return Polygon(shell=shell, holes=holes)

    @classmethod
    def make_circle(
        cls, diameter_mm: float, resolution: int = 32
    ) -> Tuple[Polygon, str]:
        r = diameter_mm / 2.0
        poly = Point(r, r).buffer(r, quad_segs=resolution)
        return cls.normalize_to_origin(poly), f"circle_d{int(diameter_mm)}mm"

    @classmethod
    def make_hollow_ring(
        cls,
        outer_diam_mm: float,
        inner_diam_mm: float,
        resolution: int = 32,
    ) -> Tuple[Polygon, str]:
        """Scenario 1 & 2: A washer/ring with an internal hole."""
        if inner_diam_mm >= outer_diam_mm:
            raise ValueError("inner_diam_mm must be smaller than outer_diam_mm")
        r_out = outer_diam_mm / 2.0
        r_in = inner_diam_mm / 2.0
        outer = Point(r_out, r_out).buffer(r_out, quad_segs=resolution)
        inner = Point(r_out, r_out).buffer(r_in, quad_segs=resolution)
        ring = outer.difference(inner)
        return (
            cls.normalize_to_origin(ring),
            f"ring_od{int(outer_diam_mm)}_id{int(inner_diam_mm)}mm",
        )

    @classmethod
    def make_rectangle(
        cls, width_mm: float, height_mm: float
    ) -> Tuple[Polygon, str]:
        poly = Polygon(
            [(0, 0), (width_mm, 0), (width_mm, height_mm), (0, height_mm)]
        )
        return (
            cls.normalize_to_origin(poly),
            f"rect_{int(width_mm)}x{int(height_mm)}mm",
        )

    @classmethod
    def make_l_bracket(
        cls, leg_w_mm: float, leg_h_mm: float, thickness_mm: float
    ) -> Tuple[Polygon, str]:
        t = thickness_mm
        coords = [
            (0, 0),
            (leg_w_mm, 0),
            (leg_w_mm, t),
            (t, t),
            (t, leg_h_mm),
            (0, leg_h_mm),
        ]
        return (
            cls.normalize_to_origin(Polygon(coords)),
            f"l_bracket_{int(leg_w_mm)}x{int(leg_h_mm)}mm",
        )

    @classmethod
    def save_part_to_dxf(cls, poly: Polygon, dxf_path: str) -> None:
        doc = ezdxf.new("R2010")
        doc.units = 4
        msp = doc.modelspace()
        doc.layers.add(name="PART_OUTER", color=3)  # Green
        doc.layers.add(name="PART_INNER_CUTS", color=2)  # Yellow

        outer_pts = list(poly.exterior.coords)
        msp.add_lwpolyline(
            outer_pts, close=True, dxfattribs={"layer": "PART_OUTER"}
        )
        for interior in poly.interiors:
            msp.add_lwpolyline(
                list(interior.coords),
                close=True,
                dxfattribs={"layer": "PART_INNER_CUTS"},
            )
        doc.saveas(dxf_path)

    @classmethod
    def load_part_from_dxf(cls, dxf_path: str) -> Polygon:
        doc = ezdxf.readfile(dxf_path)
        msp = doc.modelspace()
        if doc.units not in (0, 4):
            raise ValueError("ERR_DXF_UNITS: Only millimeter or explicitly unitless-mm files are supported")
        loops: List[Polygon] = []
        for entity in msp:
            if entity.dxftype() != "LWPOLYLINE":
                raise ValueError("ERR_DXF_ENTITY: Only closed straight LWPOLYLINE loops are supported")
            if not entity.closed or abs(entity.dxf.elevation) > 1e-9 or tuple(entity.dxf.extrusion) != (0.0, 0.0, 1.0):
                raise ValueError("ERR_DXF_NOT_PLANAR_CLOSED")
            if any(abs(p[4]) > 1e-12 for p in entity.get_points()):
                raise ValueError("ERR_DXF_BULGE: Arc bulges are not supported")
            poly = Polygon([(p[0], p[1]) for p in entity.get_points("xy")])
            if poly.is_empty or not poly.is_valid or poly.area <= 0:
                raise ValueError("ERR_DXF_INVALID_LOOP")
            loops.append(poly)
        if not loops:
            raise ValueError("ERR_DXF_EMPTY")
        loops.sort(key=lambda g: g.area, reverse=True)
        outer = loops[0]
        holes = loops[1:]
        if any(not outer.contains(h) or outer.boundary.intersects(h) for h in holes):
            raise ValueError("ERR_DXF_MULTIPLE_OUTERS")
        if any(a.intersects(b) for i,a in enumerate(holes) for b in holes[i+1:]):
            raise ValueError("ERR_DXF_OVERLAPPING_OR_NESTED_HOLES")
        poly = Polygon(outer.exterior, [h.exterior for h in holes])
        if not poly.is_valid:
            raise ValueError("ERR_DXF_INVALID_TOPOLOGY")
        return cls.normalize_to_origin(poly)
