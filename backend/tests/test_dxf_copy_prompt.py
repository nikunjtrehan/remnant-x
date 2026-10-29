import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory


@pytest.mark.parametrize('instruction', [
    'Make 50 copies of the uploaded DXF',
    'Cut 50 of the uploaded DXF',
])
def test_uploaded_dxf_copy_phrasing_with_cloud_unavailable(tmp_path, instruction):
    app = create_app(str(tmp_path / 'warehouse.db'), str(tmp_path / 'artifacts'))
    app.state.llm.chat_completion = lambda **kwargs: {'ok': False, 'error': 'offline test'}
    client = TestClient(app)
    fixture = tmp_path / 'vendor.dxf'
    CADPartFactory.save_part_to_dxf(box(0, 0, 12, 8), str(fixture))
    uploaded = client.post('/api/v1/upload-dxf', files={
        'file': ('vendor.dxf', fixture.read_bytes(), 'application/dxf')})
    assert uploaded.status_code == 200
    response = client.post('/api/v1/parse-order', json={
        'prompt': instruction + ' from 3 mm ss304 sheet, kerf 1 mm',
        'uploaded_dxf_files': [uploaded.json()['dxf_path']],
    })
    assert response.status_code == 200, response.text
    order = response.json()['order']
    assert order['material'] == 'ss304' and order['thickness_mm'] == 3
    assert order['parts'][0]['quantity'] == 50
    assert order['parts'][0]['dxf_path'] == uploaded.json()['dxf_path']
    assert response.json()['llm_trace']['provider'] == 'local-deterministic-fallback'
