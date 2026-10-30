"""Regression cases for the missing requirements found by the live benchmark."""
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from shapely.geometry import Polygon, box

from backend.api import create_app
from backend.db_and_parts import CADPartFactory
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.order_intent import inspect_order_prompt, check_order_intent
from benchmarks.order_interpretation import cases


class FixedModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def chat_completion(self, **kwargs):
        self.calls += 1
        return {'ok': True, 'provider': 'test-model', 'model': 'test-model',
                'parsed_json': deepcopy(self.payload), 'content': '', 'reasoning_content': '',
                'usage': {}, 'latency_ms': 0, 'error': None}


@pytest.mark.parametrize('case', cases(), ids=lambda c: c['id'])
def test_frozen_benchmark_requirements_are_grounded(case, tmp_path):
    """All 15 complete cases remain expressible; all five unsafe inputs stop before AI."""
    for name, poly in [('rectangle_40x30.dxf', box(0, 0, 40, 30)),
                       ('plate_60x40_hole_20x10.dxf', Polygon([(0, 0), (60, 0), (60, 40), (0, 40)],
                                                             [[(20, 15), (40, 15), (40, 25), (20, 25)]]))]:
        CADPartFactory.save_part_to_dxf(poly, str(tmp_path/name))
    payload = deepcopy(case['expected'])
    if payload:
        for i, part in enumerate(payload['parts']):
            part['part_id'] = f'P_{i}'
            if part['shape_type'] == 'dxf_file':
                part['dxf_path'] = str(tmp_path/part['dxf_path'])
    model = FixedModel(payload)
    orch = SparkWarehouseOrchestrator(None, model)
    if payload is None:
        with pytest.raises(ValueError, match='ERR_ORDER_NEEDS_CLARIFICATION'):
            orch.parse_natural_language_order_via_spark(case['prompt'])
        assert model.calls == 0
    else:
        spec = orch.parse_natural_language_order_via_spark(case['prompt'], [str(tmp_path/n) for n in case['uploads']])
        assert spec.material == payload['material']
        assert spec.thickness_mm == payload['thickness_mm']
        assert sum(p.quantity for p in spec.parts) == sum(p['quantity'] for p in payload['parts'])
        assert model.calls == 1


@pytest.mark.parametrize('change', ['quantity', 'diameter', 'thickness', 'material', 'kerf', 'extra_part'])
def test_schema_valid_model_changes_cannot_override_customer_requirements(change):
    payload = {'material': 'steel', 'thickness_mm': 3, 'kerf_mm': 1,
               'parts': [{'part_id': 'P', 'shape_type': 'circle', 'quantity': 5, 'diameter_mm': 20}]}
    if change == 'quantity': payload['parts'][0]['quantity'] = 6
    elif change == 'diameter': payload['parts'][0]['diameter_mm'] = 100
    elif change == 'thickness': payload['thickness_mm'] = 1
    elif change == 'material': payload['material'] = 'aluminum'
    elif change == 'kerf': payload['kerf_mm'] = 2
    elif change == 'extra_part': payload['parts'].append({'part_id': 'Q', 'shape_type': 'circle', 'quantity': 1, 'diameter_mm': 10})
    with pytest.raises(ValueError, match='ERR_ORDER_NEEDS_CLARIFICATION'):
        SparkWarehouseOrchestrator(None, FixedModel(payload)).parse_natural_language_order_via_spark(
            'Cut 5 circles of 20 mm from 3 mm steel sheet, kerf 1 mm.')


@pytest.mark.parametrize('prompt', [c['prompt'] for c in cases() if c['expected'] is None])
@pytest.mark.parametrize('endpoint', ['/api/v1/execute-pipeline', '/api/v1/parse-order'])
def test_pipeline_cannot_commit_an_incomplete_or_contradictory_prompt(prompt, endpoint, tmp_path, monkeypatch):
    model = FixedModel(None)
    monkeypatch.setattr('backend.api.LiveModelClient', lambda: model)
    db_path = tmp_path/'untouched.db'
    app = create_app(str(db_path), str(tmp_path/'artifacts'))
    with TestClient(app) as client:
        body = {'prompt': prompt}
        if endpoint.endswith('execute-pipeline'):
            body['commit_cuts_to_db'] = True
        response = client.post(endpoint, json=body)
    assert response.status_code == 422
    assert 'ERR_ORDER_NEEDS_CLARIFICATION' in response.json()['detail']
    assert model.calls == 0
    assert not db_path.exists()


@pytest.mark.parametrize('size', ['40x30mm', '40mmx30mm', '40 mm by 30 mm'])
def test_common_rectangle_notation_remains_supported(size):
    prompt = f'Cut 2 rectangles {size} from 3 mm steel sheet.'
    spec = SparkWarehouseOrchestrator.validate_and_parse_order_dict({
        'material': 'steel', 'thickness_mm': 3, 'kerf_mm': 3,
        'parts': [{'shape_type': 'rectangle', 'quantity': 2, 'width_mm': 40, 'height_mm': 30}]})
    check_order_intent(inspect_order_prompt(prompt), spec)


def test_offline_parser_does_not_treat_stock_thickness_as_missing_disc_diameter():
    with pytest.raises(ValueError, match='ERR_ORDER_NEEDS_CLARIFICATION'):
        SparkWarehouseOrchestrator.fallback_regex_parse_prompt('Cut 5 discs from 3 mm SS304 sheet, kerf 1 mm.')


@pytest.mark.parametrize('description', [
    'circular parts, each with a radius of 20 mm (2 cm)',
    'circles of radius 2 cm',
    'circles of 20 mm radius',
    'circles with diameter 40 mm',
    'circular pieces, radius 20 mm, diameter 40 mm',
])
def test_circle_radius_and_equivalent_units_are_grounded(description):
    prompt = f'Cut 10 {description}, from 3 mm thick cardboard. Use a kerf of 1 mm.'
    payload = {'material': 'cardboard', 'thickness_mm': 3, 'kerf_mm': 1,
               'parts': [{'part_id': 'DISC', 'shape_type': 'circle', 'quantity': 10, 'diameter_mm': 40}]}
    model = FixedModel(payload)
    spec = SparkWarehouseOrchestrator(None, model).parse_natural_language_order_via_spark(prompt)
    assert spec.parts[0].diameter_mm == 40
    assert spec.parts[0].quantity == 10
    assert model.calls == 1
    payload['parts'][0]['diameter_mm'] = 20
    with pytest.raises(ValueError, match='ERR_ORDER_NEEDS_CLARIFICATION'):
        check_order_intent(inspect_order_prompt(prompt), payload)


@pytest.mark.parametrize('description', [
    'radius 20 mm (3 cm)',
    'radius 20 mm, diameter 20 mm',
    'radius 20 mm and radius 30 mm',
    'diameter 40 mm and diameter 50 mm',
    'radius 20 mm and 30 mm',
    '40x30mm',
])
def test_conflicting_circle_measurements_stop_before_model(description):
    model = FixedModel(None)
    with pytest.raises(ValueError, match='ERR_ORDER_NEEDS_CLARIFICATION'):
        SparkWarehouseOrchestrator(None, model).parse_natural_language_order_via_spark(
            f'Cut 10 circular parts with {description} from 3 mm cardboard, kerf 1 mm.')
    assert model.calls == 0
