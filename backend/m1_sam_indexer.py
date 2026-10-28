from dataclasses import dataclass, field
import os
from typing import Any, Dict, List, Optional, Tuple
import cv2
import ezdxf
import numpy as np
from shapely.geometry import Polygon

from backend.llm_client import LiveModelClient
from backend.sam_client import segment_image
import time
import math


@dataclass
class StationCalibrationConfig:
    """Physical dimensions of the Dedicated Fiducial Indexing Station."""

    table_width_mm: float = 600.0  # Outer-left edge of ID 0 to Outer-right edge of ID 1
    table_height_mm: float = 450.0  # Outer-top edge of ID 0 to Outer-bottom edge of ID 3
    marker_size_mm: float = 50.0  # Physical size of the black ArUco square core
    px_per_mm: float = 2.0  # Orthographic resolution (2 pixels = 1.0 mm)
    max_scale_drift_mm: float = 1.5  # Fail-closed tolerance on 16-point marker check


@dataclass
class CalibrationReport:
    warped_bgr: np.ndarray
    camera_angle_deg: Optional[float]
    measured_marker_mm: float
    scale_drift_mm: float


@dataclass
class IndexedRemnantResult:
    status: str
    camera_angle_deg: Optional[float]
    measured_marker_mm: float
    scale_drift_mm: float
    outer_area_mm2: float
    usable_area_mm2: float
    hole_count: int
    outer_polygon_mm: List[Tuple[float, float]]
    interior_holes_mm: List[List[Tuple[float, float]]]
    dxf_path: str
    vision_audit: Dict[str, Any] = field(default_factory=dict)
    timings_ms: Dict[str, float] = field(default_factory=dict)


class RemnantOpticalIndexer:
    """Module 1: Optical Remnant Indexer.

    Combines 16-point planar homography calibration & topological CAD
    vectorization (Part 1A) with live Meta SAM 3.1 / Muse Spark multimodal
    surface inspection & foreground mask extraction (Part 1B).
    """

    def __init__(
        self,
        config: StationCalibrationConfig,
        llm_client: Optional[LiveModelClient] = None,
    ):
        if not all(math.isfinite(v) and v > 0 for v in (config.table_width_mm, config.table_height_mm, config.marker_size_mm, config.px_per_mm)):
            raise ValueError("ERR_INVALID_STATION_DIMENSIONS")
        if config.marker_size_mm * 2 >= min(config.table_width_mm, config.table_height_mm):
            raise ValueError("ERR_INVALID_STATION_LAYOUT")
        self.cfg = config
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self.detector_params = cv2.aruco.DetectorParameters()
        self.detector = cv2.aruco.ArucoDetector(
            self.aruco_dict, self.detector_params
        )
        self.llm = llm_client or LiveModelClient()
        self.last_vision_audit: Dict[str, Any] = {}

    def calibrate_and_flatten(self, img_bgr: np.ndarray) -> CalibrationReport:
        """Part 1A (Step 1): Detects 4 corner ArUco markers (16 total corner points),
        rectifies perspective tilt into flat millimeter space, and cross-checks
        the physical ArUco marker size to prevent scale hallucination.
        """
        corners, ids, _ = self.detector.detectMarkers(img_bgr)
        if ids is None:
            raise ValueError(
                "ERR_NO_MARKERS: 0/4 ArUco markers detected. Ensure white quiet-zone"
                " borders are visible."
            )

        detected_map: Dict[int, np.ndarray] = {}
        for marker_corners, marker_id in zip(corners, ids.flatten()):
            if int(marker_id) in (0, 1, 2, 3):
                detected_map[int(marker_id)] = marker_corners[0]  # (4, 2) TL, TR, BR, BL

        missing = [m for m in (0, 1, 2, 3) if m not in detected_map]
        if missing:
            raise ValueError(
                f"ERR_FIDUCIAL_OCCLUDED: Missing ArUco Marker IDs {missing}. "
                "All 4 station corners (ID 0, 1, 2, 3) must remain unobstructed."
            )

        W = self.cfg.table_width_mm
        H = self.cfg.table_height_mm
        S = self.cfg.marker_size_mm
        scale = self.cfg.px_per_mm

        dst_16_mm = {
            0: np.array([[0, 0], [S, 0], [S, S], [0, S]], dtype=np.float32),
            1: np.array(
                [[W - S, 0], [W, 0], [W, S], [W - S, S]], dtype=np.float32
            ),
            2: np.array(
                [[W - S, H - S], [W, H - S], [W, H], [W - S, H]], dtype=np.float32
            ),
            3: np.array(
                [[0, H - S], [S, H - S], [S, H], [0, H]], dtype=np.float32
            ),
        }

        src_pts = np.vstack([detected_map[i] for i in (0, 1, 2, 3)])
        dst_pts = np.vstack([dst_16_mm[i] * scale for i in (0, 1, 2, 3)])

        H_matrix, _ = cv2.findHomography(src_pts, dst_pts, method=0)

        # A planar homography alone cannot establish camera angle without intrinsics.
        est_angle_deg = None
        if H_matrix is None or not np.isfinite(H_matrix).all():
            raise ValueError("ERR_INVALID_HOMOGRAPHY")

        margin_mm = 15.0
        margin_px = int(round(margin_mm * scale))

        dst_pts_padded = np.vstack(
            [(dst_16_mm[i] + margin_mm) * scale for i in (0, 1, 2, 3)]
        )
        H_padded, _ = cv2.findHomography(src_pts, dst_pts_padded, method=0)

        padded_w_px = int(round((W + 2 * margin_mm) * scale))
        padded_h_px = int(round((H + 2 * margin_mm) * scale))
        warped_padded = cv2.warpPerspective(
            img_bgr, H_padded, (padded_w_px, padded_h_px)
        )

        warped_check = cv2.copyMakeBorder(
            warped_padded, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255)
        )
        w_corners, w_ids, _ = self.detector.detectMarkers(warped_check)
        if w_ids is None or len(w_corners) < 4:
            raise ValueError(
                "ERR_CALIBRATION_DRIFT: Rectified markers unreadable; check"
                " aspect-ratio inputs."
            )

        out_w_px = int(round(W * scale))
        out_h_px = int(round(H * scale))
        warped_bgr = warped_padded[
            margin_px : margin_px + out_h_px, margin_px : margin_px + out_w_px
        ]

        measured_sides_mm: List[float] = []
        for mid in (0, 1, 2, 3):
            raw_c = detected_map[mid]
            pts_h = cv2.perspectiveTransform(
                raw_c.reshape(-1, 1, 2).astype(np.float32), H_matrix
            ).reshape(4, 2)
            pts_mm = pts_h / scale
            w_mm = float(np.linalg.norm(pts_mm[1] - pts_mm[0]))
            h_mm = float(np.linalg.norm(pts_mm[3] - pts_mm[0]))
            aspect_mismatch = abs((w_mm / max(h_mm, 1e-5)) - 1.0)
            if aspect_mismatch > 0.12:
                raise ValueError(
                    "ERR_CALIBRATION_DRIFT: Table width/height aspect mismatch"
                    f" detected (distortion={aspect_mismatch:.2f})."
                )
            measured_sides_mm.extend([w_mm, h_mm])

        measured_marker_mm = round(float(np.mean(measured_sides_mm)), 2)
        scale_drift_mm = round(abs(measured_marker_mm - S), 2)

        if scale_drift_mm > self.cfg.max_scale_drift_mm:
            raise ValueError(
                f"ERR_CALIBRATION_DRIFT: Marker measured {measured_marker_mm}mm vs"
                f" expected {S}mm."
            )

        return CalibrationReport(
            warped_bgr=warped_bgr,
            camera_angle_deg=est_angle_deg,
            measured_marker_mm=measured_marker_mm,
            scale_drift_mm=scale_drift_mm,
        )

    def mask_out_fiducial_corners(
        self, warped_bgr: np.ndarray, margin_mm: float = 15.0
    ) -> np.ndarray:
        """Blanks out the 4 ArUco corner zones on the rectified image so they are
        never segmented as part of the metal/cardboard remnant.
        """
        clean = warped_bgr.copy()
        cut_px = int(round((self.cfg.marker_size_mm + margin_mm) * self.cfg.px_per_mm))
        h_px, w_px = clean.shape[:2]
        clean[0:cut_px, 0:cut_px] = 0
        clean[0:cut_px, w_px - cut_px : w_px] = 0
        clean[h_px - cut_px : h_px, w_px - cut_px : w_px] = 0
        clean[h_px - cut_px : h_px, 0:cut_px] = 0
        return clean

    def build_topological_polygon(
        self,
        binary_mask: np.ndarray,
        epsilon_mm: float = 0.0,
        min_hole_area_mm2: float = 0.0,
    ) -> Polygon:
        """Part 1A (Step 2): Converts a binary segmentation mask (255 = solid stock, 0 = background/holes)
        into a clean Shapely Polygon with interior cutout holes using 2-level
        C-COMP hierarchy and Douglas-Peucker simplification.
        """
        contours, hierarchy = cv2.findContours(
            binary_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        if hierarchy is None or len(contours) == 0:
            raise ValueError("ERR_NO_SHEET_FOUND: Mask contains no valid contours.")

        hierarchy = hierarchy[0]
        scale = self.cfg.px_per_mm

        best_outer_idx = -1
        max_area = 0.0
        for idx, cnt in enumerate(contours):
            if hierarchy[idx][3] == -1:
                area = cv2.contourArea(cnt)
                if area > max_area:
                    max_area = area
                    best_outer_idx = idx

        if best_outer_idx == -1 or (max_area / (scale * scale)) < 1000.0:
            raise ValueError(
                "ERR_SHEET_TOO_SMALL: No valid remnant sheet boundary detected."
            )
        if sum(1 for i, c in enumerate(contours) if hierarchy[i][3] == -1 and cv2.contourArea(c) / (scale * scale) >= 1.0) > 1:
            raise ValueError("ERR_MULTIPLE_SHEETS: mask contains disconnected stock; index each sheet separately")

        eps_px = epsilon_mm * scale
        outer_approx = cv2.approxPolyDP(contours[best_outer_idx], eps_px, True)
        outer_pts_mm = [
            (round(float(pt[0][0]) / scale, 2), round(float(binary_mask.shape[0] - pt[0][1]) / scale, 2))
            for pt in outer_approx
        ]

        interior_holes_mm: List[List[Tuple[float, float]]] = []
        child_idx = hierarchy[best_outer_idx][2]
        while child_idx != -1:
            hole_cnt = contours[child_idx]
            hole_area_mm2 = cv2.contourArea(hole_cnt) / (scale * scale)
            if hole_area_mm2 >= min_hole_area_mm2:
                hole_approx = cv2.approxPolyDP(hole_cnt, eps_px, True)
                if len(hole_approx) >= 3:
                    hole_pts_mm = [
                        (
                            round(float(pt[0][0]) / scale, 2),
                            round(float(binary_mask.shape[0] - pt[0][1]) / scale, 2),
                        )
                        for pt in hole_approx
                    ]
                    interior_holes_mm.append(hole_pts_mm)
            child_idx = hierarchy[child_idx][0]

        poly = Polygon(shell=outer_pts_mm, holes=interior_holes_mm)
        if poly.is_empty or not poly.is_valid:
            raise ValueError("ERR_INVALID_MASK_TOPOLOGY: recapture image rather than repairing geometry")
        return poly

    @staticmethod
    def export_remnant_dxf(poly: Polygon, dxf_path: str) -> None:
        """Part 1A (Step 3): Exports the indexed Shapely Polygon to a CAD .DXF file."""
        doc = ezdxf.new("R2010")
        doc.units = 4
        msp = doc.modelspace()
        doc.layers.add(name="OUTER_PERIMETER", color=4)  # Cyan
        doc.layers.add(name="INTERNAL_HOLES", color=1)  # Red

        outer_coords = list(poly.exterior.coords)
        msp.add_lwpolyline(
            outer_coords, close=True, dxfattribs={"layer": "OUTER_PERIMETER"}
        )
        for interior in poly.interiors:
            msp.add_lwpolyline(
                list(interior.coords),
                close=True,
                dxfattribs={"layer": "INTERNAL_HOLES"},
            )
        doc.saveas(dxf_path)

    def fetch_sam3_mask(
        self, clean_warped_bgr: np.ndarray, use_live_vision_audit: bool = False,
        segmentation_mode: str = "sam", concept: str = "sheet", object_id=None,
        use_clahe: bool = False,
        box_prompt=None,
    ) -> np.ndarray:
        """SAM is the default. Local thresholding is an explicitly labeled demo mode.

        CLAHE is opt-in pending paired testing on the user's actual station.
        Surface QA is advisory and never substitutes for a segmentation mask.
        """
        if clean_warped_bgr is None or clean_warped_bgr.size == 0:
            raise ValueError("ERR_EMPTY_IMAGE")
        started = time.perf_counter()
        image = clean_warped_bgr
        if use_clahe:
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
            image = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        if segmentation_mode == "sam":
            binary, trace = segment_image(self.llm, image, concept, object_id, box_prompt)
        elif segmentation_mode == "local_threshold":
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            trace = {"source": "local_threshold", "model": None, "physical_accuracy_validated": False}
        else:
            raise ValueError("ERR_SEGMENTATION_MODE")
        trace.update({"clahe_enabled": use_clahe, "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                      "physical_accuracy_validated": False, "coordinate_frame": "station_mm_x_right_y_up"})
        self.last_vision_audit = {"segmentation": trace}
        if use_live_vision_audit:
            _, buf = cv2.imencode(".png", image)
            res = self.llm.chat_completion(
                system_prompt='Inspect surface only. Return JSON with surface_observations and uncertainties. Do not certify dimensions or material grade.',
                user_prompt="Inspect this rectified sheet.", image_bytes=buf.tobytes(), prefer_provider="meta", max_tokens=1024)
            self.last_vision_audit["surface_advice"] = {"ok": res["ok"], "audit": res.get("parsed_json"), "provider": res.get("provider")}
        return binary

    def index_remnant_from_image(
        self,
        img_bgr: np.ndarray,
        dxf_out_path: str,
        use_live_vision_audit: bool = False,
        segmentation_mode: str = "sam", concept: str = "sheet", object_id=None, use_clahe: bool = False,
        box_prompt=None,
    ) -> IndexedRemnantResult:
        """Full end-to-end Module 1 pipeline:
        16-point ArUco Homography -> Fiducial Masking -> Foreground Mask ->
        Topological Polygon + Interior Holes -> CAD DXF export.
        """
        started = time.perf_counter()
        cal = self.calibrate_and_flatten(img_bgr)
        timings = {"calibration_ms": round((time.perf_counter() - started) * 1000, 2)}
        stage = time.perf_counter()
        clean_bgr = self.mask_out_fiducial_corners(cal.warped_bgr)
        mask = self.fetch_sam3_mask(
            clean_bgr, use_live_vision_audit=use_live_vision_audit,
            segmentation_mode=segmentation_mode, concept=concept, object_id=object_id, use_clahe=use_clahe, box_prompt=box_prompt
        )
        timings["segmentation_ms"] = round((time.perf_counter() - stage) * 1000, 2)
        stage = time.perf_counter()
        poly = self.build_topological_polygon(mask)
        timings["vectorization_ms"] = round((time.perf_counter() - stage) * 1000, 2)
        stage = time.perf_counter()
        if dxf_out_path:
            os.makedirs(os.path.dirname(os.path.abspath(dxf_out_path)), exist_ok=True)
            self.export_remnant_dxf(poly, dxf_out_path)
        timings["dxf_export_ms"] = round((time.perf_counter() - stage) * 1000, 2)
        timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)

        outer_poly = Polygon(poly.exterior.coords)
        outer_area = round(float(outer_poly.area), 2)
        usable_area = round(float(poly.area), 2)
        outer_pts = [(round(float(x), 2), round(float(y), 2)) for x, y in poly.exterior.coords]
        holes_pts = [
            [(round(float(x), 2), round(float(y), 2)) for x, y in ring.coords]
            for ring in poly.interiors
        ]

        return IndexedRemnantResult(
            status="INDEXED_OK",
            camera_angle_deg=cal.camera_angle_deg,
            measured_marker_mm=cal.measured_marker_mm,
            scale_drift_mm=cal.scale_drift_mm,
            outer_area_mm2=outer_area,
            usable_area_mm2=usable_area,
            hole_count=len(poly.interiors),
            outer_polygon_mm=outer_pts,
            interior_holes_mm=holes_pts,
            dxf_path=dxf_out_path,
            vision_audit=self.last_vision_audit,
            timings_ms=timings,
        )
