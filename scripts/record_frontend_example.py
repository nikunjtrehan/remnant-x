"""Reproduce the public synthetic showcase through the actual offline backend.

No API keys, physical user photographs or warehouse files are used. The example
is local-threshold geometry, not evidence of a live SAM inference.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon

from backend.db_and_parts import RemnantWarehouseDB
from backend.llm_client import LiveModelClient
from backend.m1_sam_indexer import RemnantOpticalIndexer, StationCalibrationConfig
from backend.pipeline import execute_pipeline
from backend.schemas import FullPipelineRequest


def station_image(missing=-1):
    image = np.full((1000, 1300, 3), 28, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for marker, (x, y) in enumerate([(50, 50), (1150, 50), (1150, 850), (50, 850)]):
        if marker == missing:
            continue
        image[y-16:y+116, x-16:x+116] = 255
        core = cv2.aruco.generateImageMarker(dictionary, marker, 100)
        image[y:y+100, x:x+100] = cv2.cvtColor(core, cv2.COLOR_GRAY2BGR)
    image[300:700, 350:950] = (180, 190, 200)
    cv2.fillPoly(image, [np.array([(450, 390), (500, 390), (500, 540),
                                 (700, 540), (700, 590), (450, 590)])], (28, 28, 28))
    return image


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / 'Front End' / 'public' / 'example'
    destination.mkdir(parents=True, exist_ok=True)
    image = station_image()
    cv2.imwrite(str(destination / 'station.png'), image)
    indexer = RemnantOpticalIndexer(StationCalibrationConfig())
    indexed = indexer.index_remnant_from_image(image, '', segmentation_mode='local_threshold')
    db = RemnantWarehouseDB(':memory:')
    db.upsert_remnant('EXAMPLE_LCUTOUT_01', 'steel', 3,
                     Polygon(indexed.outer_polygon_mm, indexed.interior_holes_mm), source='local_threshold')
    order = {'order_id': 'SECOND_LIFE_01', 'material': 'steel', 'thickness_mm': 3, 'kerf_mm': 1,
             'parts': [
                 {'part_id': 'PLATE', 'shape_type': 'rectangle', 'width_mm': 45, 'height_mm': 30, 'quantity': 12},
                 {'part_id': 'RING', 'shape_type': 'ring', 'outer_diam_mm': 36, 'inner_diam_mm': 16, 'quantity': 8},
                 {'part_id': 'DISC', 'shape_type': 'circle', 'diameter_mm': 16, 'quantity': 8},
             ]}
    result = execute_pipeline(FullPipelineRequest(order=order, allow_demo_stock=True, search_iterations=0),
                              db, LiveModelClient(), destination)
    assert result['nesting']['total_placed'] == result['nesting']['total_requested']
    assert all(p['verification']['verified_safe'] for p in result['gcode_programs'])
    evidence = {'recorded_at': datetime.now(timezone.utc).isoformat(),
                'source': 'synthetic station; OpenCV local_threshold; actual NFP placement and G-code verification',
                'image_sha256': hashlib.sha256((destination / 'station.png').read_bytes()).hexdigest(),
                'station': {'table_width_mm': 600, 'table_height_mm': 450, 'marker_size_mm': 50},
                'indexing_timings_ms': indexed.timings_ms, 'order': order, 'result': result}
    (destination / 'recording.json').write_text(json.dumps(evidence, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({'parts': result['nesting']['total_placed'], 'sheets': result['metrics']['sheets_used'],
                      'utilization_pct': result['metrics']['usable_area_utilization_pct'],
                      'total_ms': result['timings_ms']['total_ms']}))


if __name__ == '__main__':
    main()
