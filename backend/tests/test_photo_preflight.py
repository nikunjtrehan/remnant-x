import base64

import cv2
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.m1_sam_indexer import RemnantOpticalIndexer
from backend.tests.test_module1_calibration import _create_synthetic_station_image


def photo_payload(missing=-1):
    image = _create_synthetic_station_image(occlude_marker_id=missing)
    _, png = cv2.imencode('.png', image)
    return {"image_base64": base64.b64encode(png).decode(), "table_width_mm": 600,
            "table_height_mm": 450, "marker_size_mm": 50}


def test_preflight_returns_real_marker_coordinates_and_rectified_frame_without_side_effects(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight must never call segmentation")
    monkeypatch.setattr(RemnantOpticalIndexer, 'fetch_sam3_mask', forbidden)
    db, artifacts = tmp_path / 'unused.db', tmp_path / 'artifacts'
    client = TestClient(create_app(str(db), str(artifacts)))
    result = client.post('/api/v1/photo-preflight', json=photo_payload()).json()
    assert result['ready'] and result['detected_ids'] == [0, 1, 2, 3]
    assert len(result['markers']) == 4
    assert all(len(marker['corners_px']) == 4 for marker in result['markers'])
    assert result['frame'] == {"width_px": 1200, "height_px": 900,
                               "width_mm": 600, "height_mm": 450, "pixels_per_mm": 2}
    assert result['rectified_image_base64'].startswith('data:image/jpeg;base64,')
    assert not db.exists() and not artifacts.exists()


@pytest.mark.parametrize('missing', [0, 1, 2, 3])
def test_missing_marker_is_actionable_and_actual_indexing_still_rejects_it(tmp_path, monkeypatch, missing):
    monkeypatch.setattr(RemnantOpticalIndexer, 'fetch_sam3_mask', lambda *a, **k: pytest.fail('No SAM'))
    client = TestClient(create_app(str(tmp_path / 'unused.db'), str(tmp_path / 'out')))
    payload = photo_payload(missing)
    result = client.post('/api/v1/photo-preflight', json=payload).json()
    assert not result['ready']
    assert result['missing_ids'] == [missing]
    assert result['issues'][0]['code'] == 'ERR_FIDUCIAL_OCCLUDED'
    assert 'rectified_image_base64' not in result
    response = client.post('/api/v1/index-remnant', json={**payload, 'material': 'steel', 'thickness_mm': 3})
    assert response.status_code == 422
    assert not (tmp_path / 'unused.db').exists()


def test_bad_calibration_and_unreadable_images_do_not_pass(tmp_path):
    client = TestClient(create_app(str(tmp_path / 'unused.db')))
    result = client.post('/api/v1/photo-preflight', json={**photo_payload(), 'table_width_mm': 900}).json()
    assert not result['ready'] and result['issues'][0]['code'] == 'ERR_CALIBRATION_DRIFT'
    assert client.post('/api/v1/photo-preflight', json={'image_base64': 'not an image'}).status_code == 422


def test_downloads_only_dxf_files_directly_in_managed_artifact_root(tmp_path):
    root = tmp_path / 'out'
    root.mkdir()
    (root / 'example.dxf').write_text('example DXF')
    (root / 'private.env').write_text('not downloadable')
    client = TestClient(create_app(str(tmp_path / 'unused.db'), str(root)))
    assert client.get('/api/v1/artifacts/example.dxf').content == b'example DXF'
    assert client.get('/api/v1/artifacts/private.env').status_code == 404
    assert client.get('/api/v1/artifacts/missing.dxf').status_code == 404
