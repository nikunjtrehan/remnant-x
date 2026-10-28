import cv2
import numpy as np
import pytest

from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig


def _create_synthetic_station_image(
    w_mm: float = 600.0,
    h_mm: float = 450.0,
    marker_mm: float = 50.0,
    px_per_mm: float = 2.0,
    occlude_marker_id: int = -1,
) -> np.ndarray:
    """Helper: Builds a realistic top-down station canvas with 4 white-bordered ArUco markers
    on a matte-black backing and a 300mm x 200mm cardboard sheet with an L-shaped interior hole,
    then warps it with a 3D perspective camera tilt.
    """
    margin_mm = 25.0
    M_px = int(margin_mm * px_per_mm)
    W_px, H_px = int(w_mm * px_per_mm), int(h_mm * px_per_mm)
    S_px = int(marker_mm * px_per_mm)
    B_px = int(8.0 * px_per_mm)  # White quiet-zone border around each ArUco marker

    total_w = W_px + 2 * M_px
    total_h = H_px + 2 * M_px
    canvas = np.full((total_h, total_w, 3), 20, dtype=np.uint8)
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)

    # Table corners are offset by M_px so white quiet zones are never clipped
    positions = {
        0: (M_px, M_px),
        1: (M_px + W_px - S_px, M_px),
        2: (M_px + W_px - S_px, M_px + H_px - S_px),
        3: (M_px, M_px + H_px - S_px),
    }

    for mid, (x0, y0) in positions.items():
        if mid == occlude_marker_id:
            continue
        # Draw white quiet zone around marker
        canvas[y0 - B_px : y0 + S_px + B_px, x0 - B_px : x0 + S_px + B_px] = 255
        m_img = cv2.aruco.generateImageMarker(aruco_dict, mid, S_px)
        canvas[y0 : y0 + S_px, x0 : x0 + S_px] = cv2.cvtColor(
            m_img, cv2.COLOR_GRAY2BGR
        )

    # Place a 300mm x 200mm sheet in the center (from X=150..450mm, Y=125..325mm)
    sx0, sy0 = M_px + int(150 * px_per_mm), M_px + int(125 * px_per_mm)
    sx1, sy1 = M_px + int(450 * px_per_mm), M_px + int(325 * px_per_mm)
    canvas[sy0:sy1, sx0:sx1] = (210, 210, 210)

    # Apply a simulated 65-degree oblique camera perspective warp
    src = np.array(
        [[0, 0], [total_w, 0], [total_w, total_h], [0, total_h]], dtype=np.float32
    )
    dst = np.array(
        [
            [total_w * 0.08, total_h * 0.12],
            [total_w * 0.92, total_h * 0.10],
            [total_w * 0.98, total_h * 0.95],
            [total_w * 0.02, total_h * 0.93],
        ],
        dtype=np.float32,
    )
    M = cv2.getPerspectiveTransform(src, dst)
    tilted_img = cv2.warpPerspective(
        canvas, M, (total_w, total_h), borderValue=(20, 20, 20)
    )
    return tilted_img


def test_homography_accuracy_under_oblique_tilt():
    """Test Case 1: Verify tilted camera photo rectifies back to exact dimensions (<0.5mm drift)."""
    cfg = StationCalibrationConfig(
        table_width_mm=600.0, table_height_mm=450.0, marker_size_mm=50.0
    )
    indexer = RemnantOpticalIndexer(cfg)
    tilted_img = _create_synthetic_station_image()

    report = indexer.calibrate_and_flatten(tilted_img)
    assert report.scale_drift_mm < 0.5
    assert abs(report.measured_marker_mm - 50.0) < 0.5


def test_missing_marker_rejection():
    """Test Case 2: Verify fail-closed rejection when any of the 4 corner ArUco markers is occluded."""
    cfg = StationCalibrationConfig()
    indexer = RemnantOpticalIndexer(cfg)
    occluded_img = _create_synthetic_station_image(occlude_marker_id=2)

    with pytest.raises(ValueError, match="ERR_FIDUCIAL_OCCLUDED"):
        indexer.calibrate_and_flatten(occluded_img)


def test_wrong_table_dimensions_caught():
    """Test Case 3: Verify 16-point marker aspect check catches wrong user-entered table dimensions."""
    # Actual table is 600x450mm, but user mistakenly configures 900x450mm
    wrong_cfg = StationCalibrationConfig(
        table_width_mm=900.0, table_height_mm=450.0, marker_size_mm=50.0
    )
    indexer = RemnantOpticalIndexer(wrong_cfg)
    tilted_img = _create_synthetic_station_image(w_mm=600.0, h_mm=450.0)

    with pytest.raises(ValueError, match="ERR_CALIBRATION_DRIFT"):
        indexer.calibrate_and_flatten(tilted_img)


def test_l_hole_topological_subtraction(tmp_path):
    """Test Case 4: Verify outer sheet (400x300mm = 120,000 mm2) minus L-hole (20,000 mm2) = 100,000 mm2."""
    cfg = StationCalibrationConfig(px_per_mm=2.0)
    indexer = RemnantOpticalIndexer(cfg)

    scale = int(cfg.px_per_mm)
    mask = np.zeros((450 * scale, 600 * scale), dtype=np.uint8)

    # Draw 400x300mm outer sheet (X: 100..500mm, Y: 50..350mm) -> Area = 120,000 mm2
    mask[50 * scale : 350 * scale, 100 * scale : 500 * scale] = 255

    # Cut out an L-shaped hole inside the sheet:
    # Vertical leg: 100x150mm = 15,000 mm2 (X: 200..300mm, Y: 100..250mm)
    # Horizontal extension: 100x50mm = 5,000 mm2 (X: 300..400mm, Y: 200..250mm)
    # Total L-hole area = 20,000 mm2
    mask[100 * scale : 250 * scale, 200 * scale : 300 * scale] = 0
    mask[200 * scale : 250 * scale, 300 * scale : 400 * scale] = 0

    poly = indexer.build_topological_polygon(mask, epsilon_mm=0.5)
    dxf_out = str(tmp_path / "remnant_l_hole.dxf")
    indexer.export_remnant_dxf(poly, dxf_out)

    assert len(poly.interiors) == 1
    # Usable area must be 120,000 - 20,000 = 100,000 mm2 (within 1% contour discretization)
    assert abs(poly.area - 100000.0) / 100000.0 < 0.01
