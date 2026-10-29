"""Read-only photo gate. Uses the same calibration checks as actual indexing."""
import base64

import cv2
import numpy as np

from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig


def decode_station_image(image_base64):
    data = base64.b64decode(image_base64.split(",")[-1], validate=True)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("ERR_DECODE_IMAGE: Choose a readable JPEG or PNG photo.")
    return image


def photo_preflight(req, llm):
    image = decode_station_image(req.image_base64)
    indexer = RemnantOpticalIndexer(StationCalibrationConfig(
        table_width_mm=req.table_width_mm, table_height_mm=req.table_height_mm,
        marker_size_mm=req.marker_size_mm), llm_client=llm)
    corners, ids, _ = indexer.detector.detectMarkers(image)
    detected = [] if ids is None else [int(i) for i in ids.flatten()]
    result = {
        "ready": False,
        "detected_ids": sorted(set(detected) & {0, 1, 2, 3}),
        "missing_ids": [i for i in range(4) if i not in detected],
        "duplicate_ids": [i for i in range(4) if detected.count(i) > 1],
        "markers": [{"id": i, "corners_px": c[0].tolist()}
                    for i, c in zip(detected, corners) if i in range(4)],
        "image_width_px": image.shape[1], "image_height_px": image.shape[0],
        "issues": [],
    }
    try:
        calibration = indexer.calibrate_and_flatten(image)
    except ValueError as exc:
        code, _, message = str(exc).partition(":")
        result["issues"] = [{"code": code, "message": message.strip() or code}]
        return result
    ok, encoded = cv2.imencode(".jpg", calibration.warped_bgr, [cv2.IMWRITE_JPEG_QUALITY, 86])
    if not ok:
        raise ValueError("ERR_PREVIEW_ENCODING")
    result.update({
        "ready": True,
        "measured_marker_mm": calibration.measured_marker_mm,
        "scale_drift_mm": calibration.scale_drift_mm,
        "rectified_image_base64": "data:image/jpeg;base64," + base64.b64encode(encoded).decode(),
        "frame": {"width_px": calibration.warped_bgr.shape[1],
                  "height_px": calibration.warped_bgr.shape[0],
                  "width_mm": req.table_width_mm, "height_mm": req.table_height_mm,
                  "pixels_per_mm": indexer.cfg.px_per_mm},
    })
    return result
