"""Opt-in live order benchmark. Never executes the manufacturing pipeline or writes inventory.

Run from the project root with .venv/Scripts/python.exe -B -m benchmarks.order_interpretation.
--prepare is offline; --pilot sends two requests; --run sends the documented repeated trials.
Only synthetic instructions and generated DXF fixture paths are sent to providers.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import statistics
import subprocess
import threading
import time

from shapely.geometry import Polygon, box
from backend.db_and_parts import CADPartFactory
from backend.llm_client import LiveModelClient
from backend.materials import explicit_prompt_materials
from backend.m2_spark_orchestrator import SparkWarehouseOrchestrator
from backend.pipeline import check_order_uploads

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.task-tmp' / 'order-benchmark'
UPLOADS = WORK / 'uploads'
PRICING = {
    'baseten': {'input': 1.25, 'cached_input': 0.15, 'output': 4.25,
                'source': 'https://www.baseten.co/library/muse-spark-open/'},
    'fireworks': {'input': 1.25, 'cached_input': 0.15, 'output': 4.25,
                 'source': 'https://fireworks.ai/models/fireworks/muse-spark-open'},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def fixture_files():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    shapes = {
        'rectangle_40x30.dxf': box(0, 0, 40, 30),
        'plate_60x40_hole_20x10.dxf': Polygon(
            [(0, 0), (60, 0), (60, 40), (0, 40)],
            [[(20, 15), (40, 15), (40, 25), (20, 25)]]),
    }
    result = []
    for name, intended in shapes.items():
        path = UPLOADS / name
        if not path.exists():
            CADPartFactory.save_part_to_dxf(intended, str(path))
        loaded = CADPartFactory.load_part_from_dxf(str(path))
        assert loaded.equals(intended), name
        result.append({'name': name, 'bounds_mm': list(loaded.bounds),
                       'area_mm2': loaded.area, 'holes': len(loaded.interiors),
                       'sha256': digest(path), 'origin': 'locally generated synthetic polygon'})
    return result


def part(shape, quantity, **fields):
    return {'shape_type': shape, 'quantity': quantity, **fields}


def case(identifier, prompt, material=None, thickness=None, kerf=None, parts=None,
         uploads=(), reason=None):
    expected = None if reason else {'material': material, 'thickness_mm': thickness,
                                    'kerf_mm': kerf, 'parts': parts}
    return {'id': identifier, 'prompt': prompt, 'uploads': list(uploads),
            'expected': expected, 'expected_action': 'reject_or_clarify' if reason else 'accept',
            'rationale': reason or 'Every scored requirement is explicit in the prompt; generated IDs are ignored.'}


def cases():
    rect, hole = 'rectangle_40x30.dxf', 'plate_60x40_hole_20x10.dxf'
    return [
        case('01_simple_circle', 'Cut 5 discs of diameter 20 mm from 3 mm steel sheet. Kerf 1 mm.',
             'steel', 3, 1, [part('circle', 5, diameter_mm=20)]),
        case('02_mild_steel_rectangle', 'Make 8 rectangular plates, width 40 mm and height 30 mm, from 2 mm mild steel. Kerf 0.8 mm.',
             'mild_steel', 2, .8, [part('rectangle', 8, width_mm=40, height_mm=30)]),
        case('03_ss304_ring', 'Cut 12 washers: outside diameter 60 mm, inside diameter 20 mm. Use 5 mm SS304 sheet and kerf 0.6 mm.',
             'ss304', 5, .6, [part('ring', 12, outer_diam_mm=60, inner_diam_mm=20)]),
        case('04_ss316_rectangle', 'Make 6 rectangles 100 mm wide by 50 mm high in 4 mm SS316. Kerf 1 mm.',
             'ss316', 4, 1, [part('rectangle', 6, width_mm=100, height_mm=50)]),
        case('05_al6061_circle', 'Cut 20 circles of diameter 30 mm from 2 mm AL6061 sheet, kerf 0.5 mm.',
             'al6061', 2, .5, [part('circle', 20, diameter_mm=30)]),
        case('06_al5052_bracket', 'Make 4 flat L-brackets from 3 mm AL5052. Overall width 80 mm, overall height 60 mm, both legs 10 mm wide. Kerf 0.7 mm.',
             'al5052', 3, .7, [part('l_bracket', 4, width_mm=80, height_mm=60, thickness_leg_mm=10)]),
        case('07_mixed_parts', 'From 3 mm steel, cut 3 discs of diameter 20 mm, 2 rectangles 40 by 30 mm, and 4 washers with outside diameter 60 mm and inside diameter 20 mm. Kerf 1 mm.',
             'steel', 3, 1, [part('circle', 3, diameter_mm=20), part('rectangle', 2, width_mm=40, height_mm=30), part('ring', 4, outer_diam_mm=60, inner_diam_mm=20)]),
        case('08_inches_to_mm', 'Cut 4 rectangles, each 2 inches wide by 1 inch high, from 1/8 inch thick AL6061 sheet. Kerf 0.5 mm. Express all dimensions in millimeters.',
             'al6061', 3.175, .5, [part('rectangle', 4, width_mm=50.8, height_mm=25.4)]),
        case('09_generic_stainless_square', 'Cut 9 square plates with 25 mm sides from 1.5 mm stainless steel. No alloy grade is specified. Kerf 0.4 mm.',
             'stainless_steel', 1.5, .4, [part('rectangle', 9, width_mm=25, height_mm=25)]),
        case('10_grain_locked', 'Make 6 rectangles, width 120 mm along the sheet X axis and height 15 mm, from 2 mm AL5052. Grain direction must be preserved: set grain_locked true. Kerf 0.5 mm.',
             'al5052', 2, .5, [part('rectangle', 6, width_mm=120, height_mm=15, grain_locked=True)]),
        case('11_corrected_quantity', 'I initially wanted 5 discs but change the quantity to 7 discs, diameter 20 mm, from 3 mm SS316. The final quantity is 7, not 5. Kerf 1 mm.',
             'ss316', 3, 1, [part('circle', 7, diameter_mm=20)]),
        case('12_dxf_quantity_50', 'Cut 50 copies of the uploaded DXF part from 3 mm SS304 sheet. Kerf 1 mm.',
             'ss304', 3, 1, [part('dxf_file', 50, dxf_path=rect)], uploads=[rect]),
        case('13_dxf_with_hole', 'Make 10 copies of the uploaded DXF, retaining its existing hole. Use 2 mm AL6061 and kerf 0.5 mm.',
             'al6061', 2, .5, [part('dxf_file', 10, dxf_path=hole)], uploads=[hole]),
        case('14_two_dxf_bindings', f'From 3 mm steel, make 12 copies of {rect} and 7 copies of {hole}. Both are uploaded DXF parts. Kerf 1 mm.',
             'steel', 3, 1, [part('dxf_file', 12, dxf_path=rect), part('dxf_file', 7, dxf_path=hole)], uploads=[rect, hole]),
        case('15_decimal_brass_ring', 'Cut 18 washers from 0.8 mm brass: outer diameter 12.5 mm, inner diameter 6.25 mm. Kerf 0.25 mm.',
             'brass', .8, .25, [part('ring', 18, outer_diam_mm=12.5, inner_diam_mm=6.25)]),
        case('16_missing_thickness', 'Cut 5 discs of diameter 20 mm from SS304 sheet. Kerf 1 mm.',
             reason='Sheet thickness is absent; no business default authorizes inventing it.'),
        case('17_missing_diameter', 'Cut 5 circular discs from 3 mm SS304 sheet. Kerf 1 mm.',
             reason='Disc diameter is absent; the part cannot be defined.'),
        case('18_undecided_quantity', 'Cut either 5 or 10 discs of diameter 20 mm from 3 mm steel. I have not decided which quantity. Kerf 1 mm.',
             reason='Quantity is explicitly undecided; neither alternative is an authorized order.'),
        case('19_unresolved_grade', 'Cut 5 discs of diameter 20 mm from 3 mm sheet, kerf 1 mm. The drawing says SS304 but procurement says SS316. I do not know which grade is required.',
             reason='The requested material grade is unresolved; a single grade must not be silently chosen.'),
        case('20_impossible_ring', 'Cut 2 washers from 3 mm steel, outer diameter 20 mm and inner diameter 30 mm. Kerf 1 mm.',
             reason='The inner diameter exceeds the outer diameter; the geometry is impossible.'),
    ]


def canonical(spec):
    raw = asdict(spec) if not isinstance(spec, dict) else spec
    groups = {}
    for p in raw['parts']:
        shape = p['shape_type']
        lock = bool(p.get('grain_locked', False))
        fields = {'shape_type': shape, 'grain_locked': lock}
        keys = {'circle': ['diameter_mm'], 'ring': ['outer_diam_mm', 'inner_diam_mm'],
                'rectangle': ['width_mm', 'height_mm'],
                'l_bracket': ['width_mm', 'height_mm', 'thickness_leg_mm'],
                'dxf_file': ['dxf_path']}[shape]
        for key in keys:
            fields[key] = Path(p[key]).name if key == 'dxf_path' else round(float(p[key]), 5)
        if shape in ('rectangle', 'l_bracket') and not lock:
            fields['width_mm'], fields['height_mm'] = sorted([fields['width_mm'], fields['height_mm']])
        key = json.dumps(fields, sort_keys=True)
        groups[key] = groups.get(key, 0) + int(p['quantity'])
    parts = [{**json.loads(key), 'quantity': quantity} for key, quantity in sorted(groups.items())]
    return {'material': raw['material'], 'thickness_mm': round(float(raw['thickness_mm']), 5),
            'kerf_mm': round(float(raw['kerf_mm']), 5), 'parts': parts}


class Capture(Exception):
    pass


class PromptCapture:
    def chat_completion(self, **kwargs):
        self.kwargs = kwargs
        raise Capture()


def request_kwargs(c):
    capture = PromptCapture()
    try:
        SparkWarehouseOrchestrator(None, capture).parse_natural_language_order_via_spark(
            c['prompt'], [str(UPLOADS / name) for name in c['uploads']])
    except Capture:
        return capture.kwargs
    raise AssertionError('Expected the production parser to request a completion.')


def estimate_cost(provider, usage):
    price = PRICING.get(provider)
    if price is None or not usage or 'prompt_tokens' not in usage or 'completion_tokens' not in usage:
        return None
    prompt, completion = usage['prompt_tokens'], usage['completion_tokens']
    details = usage.get('prompt_tokens_details') or {}
    cached = min(prompt, details.get('cached_tokens', usage.get('prompt_cache_hit_tokens', 0)) or 0)
    return round(((prompt-cached)*price['input'] + cached*price['cached_input'] + completion*price['output'])/1_000_000, 9)


class TracedClient(LiveModelClient):
    def __init__(self):
        super().__init__()
        self.calls = []

    def _post_chat(self, **kwargs):
        result = super()._post_chat(**kwargs)
        self.calls.append({**result, 'estimated_usd': estimate_cost(kwargs['provider'], result.get('usage', {}))})
        return result


def validate_response(c, payload):
    uploads = [str(UPLOADS / name) for name in c['uploads']]
    parsed = SparkWarehouseOrchestrator.validate_and_parse_order_dict(payload, uploads)
    materials = explicit_prompt_materials(c['prompt'])
    if materials and materials != {parsed.material}:
        raise ValueError('ERR_MODEL_CHANGED_MATERIAL_GRADE')
    check_order_uploads(parsed, UPLOADS.resolve())
    SparkWarehouseOrchestrator.build_cad_part_specs(parsed)
    return canonical(parsed)


def provider_trial(c, provider):
    client = TracedClient()
    kwargs = request_kwargs(c)
    cfg = client._provider_config(provider)
    if cfg is None:
        return {'provider': provider, 'accepted': False, 'failure': 'transport', 'error': 'Provider not configured', 'latency_ms': 0, 'calls': []}
    started = time.perf_counter()
    result = client._post_chat(provider=provider, url=cfg['base_url']+'/chat/completions',
        api_key=cfg['api_key'], model=cfg['model'], system_prompt=kwargs['system_prompt'],
        user_prompt=kwargs['user_prompt'], image_bytes=None, image_mime='image/png',
        max_tokens=kwargs['max_tokens'], temperature=kwargs['temperature'], timeout_sec=45.0)
    answer = {'provider': provider, 'accepted': False, 'calls': client.calls}
    if not result['ok']:
        answer.update(failure='transport', error=result.get('error', 'Provider failure'))
    else:
        try:
            answer.update(accepted=True, spec=validate_response(c, result['parsed_json']))
        except Exception as exc:
            answer.update(accepted=False, failure='validation', error=f'{type(exc).__name__}: {exc}')
    answer['latency_ms'] = round((time.perf_counter()-started)*1000, 2)
    return answer


def baseline(c):
    client = TracedClient()
    orch = SparkWarehouseOrchestrator(None, client)
    started = time.perf_counter()
    answer = {'accepted': False, 'calls': client.calls}
    try:
        spec = orch.parse_natural_language_order_via_spark(c['prompt'], [str(UPLOADS / n) for n in c['uploads']])
        check_order_uploads(spec, UPLOADS.resolve())
        orch.build_cad_part_specs(spec)
        answer.update(accepted=True, spec=canonical(spec), provider=orch.last_llm_trace.get('provider'))
    except Exception as exc:
        failure = 'transport' if client.calls and all(not call['ok'] for call in client.calls) else 'validation'
        answer.update(failure=failure, error=f'{type(exc).__name__}: {exc}')
    answer['latency_ms'] = round((time.perf_counter()-started)*1000, 2)
    return answer


def parallel(c):
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: provider_trial(c, p), ['baseten', 'fireworks']))
    valid = [r for r in results if r['accepted']]
    agree = len(valid) == 2 and valid[0]['spec'] == valid[1]['spec']
    answer = {'accepted': agree, 'provider_results': results, 'agreement': agree,
              'calls': [call for r in results for call in r['calls']],
              'latency_ms': round((time.perf_counter()-started)*1000, 2),
              'observed_first_valid_ms': min((r['latency_ms'] for r in valid), default=None)}
    if agree:
        answer['spec'] = valid[0]['spec']
    else:
        answer['failure'] = 'transport' if any(r.get('failure') == 'transport' for r in results) else 'review_required'
    return answer


def score(c, answer):
    if c['expected_action'] == 'reject_or_clarify':
        return not answer['accepted'] and answer.get('failure') != 'transport'
    return bool(answer['accepted'] and answer['spec'] == canonical(c['expected']))


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered)-1)*fraction
    lo = int(index)
    hi = min(lo+1, len(ordered)-1)
    return round(ordered[lo] + (ordered[hi]-ordered[lo])*(index-lo), 2)


def summarize(records):
    summary = {}
    for mode in ['current_failover', 'parallel_agreement']:
        rows = [r for r in records if r['mode'] == mode]
        if not rows:
            continue
        calls = [call for r in rows for call in r['calls']]
        known_cost = [call['estimated_usd'] for call in calls if call['estimated_usd'] is not None]
        correct_accepts = sum(r['correct'] and r['accepted'] for r in rows)
        summary[mode] = {
            'trials': len(rows), 'correct_outcomes': sum(r['correct'] for r in rows),
            'correct_accepts': correct_accepts,
            'wrong_accepts': sum(r['accepted'] and not r['correct'] for r in rows),
            'unnecessary_blocks': sum(not r['accepted'] and r['expected_action'] == 'accept' for r in rows),
            'safe_rejections': sum(r['correct'] and r['expected_action'] == 'reject_or_clarify' for r in rows),
            'incomplete_transport': sum(r.get('failure') == 'transport' for r in rows),
            'median_ms': round(statistics.median(r['latency_ms'] for r in rows), 2),
            'p95_ms': percentile([r['latency_ms'] for r in rows], .95),
            'provider_requests': len(calls), 'successful_provider_requests': sum(call['ok'] for call in calls),
            'reported_prompt_tokens': sum(call.get('usage', {}).get('prompt_tokens', 0) for call in calls),
            'reported_completion_tokens': sum(call.get('usage', {}).get('completion_tokens', 0) for call in calls),
            'estimated_known_usd': round(sum(known_cost), 6),
            'requests_without_cost_estimate': len(calls)-len(known_cost),
            'estimated_usd_per_correct_accept': round(sum(known_cost)/correct_accepts, 6) if correct_accepts else None,
        }
        first = [r['observed_first_valid_ms'] for r in rows if r.get('observed_first_valid_ms') is not None]
        if first:
            summary[mode]['observed_first_valid_median_ms'] = round(statistics.median(first), 2)
    return summary


def preserved_files():
    protected = [ROOT/'.env', ROOT/'warehouse.db']
    protected += list((ROOT/'backend').rglob('*.py'))
    return {str(p.relative_to(ROOT)): digest(p) for p in protected if p.is_file()}


def prepare():
    fixtures = fixture_files()
    dataset = cases()
    for c in dataset:
        if c['expected']:
            payload = json.loads(json.dumps(c['expected']))
            payload['order_id'] = 'EXPECTED'
            for i, item in enumerate(payload['parts']):
                item['part_id'] = f'EXPECTED_{i}'
                if item['shape_type'] == 'dxf_file':
                    item['dxf_path'] = str(UPLOADS/item['dxf_path'])
            assert validate_response(c, payload) == canonical(c['expected']), c['id']
    changed = json.loads(json.dumps(dataset[0]['expected']))
    changed['parts'][0]['quantity'] = 6
    assert not score(dataset[0], {'accepted': True, 'spec': canonical(changed)})
    assert not score(dataset[15], {'accepted': True, 'spec': canonical(dataset[0]['expected'])})
    dump(WORK/'cases.json', dataset)
    dump(WORK/'fixtures.json', fixtures)
    print(f'Offline preparation passed: {len(dataset)} cases, 15 complete orders, 5 reject/clarify cases, {len(fixtures)} verified DXFs.', flush=True)
    return dataset


def pilot(dataset):
    require_historical_backend()
    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(lambda p: provider_trial(dataset[0], p), ['baseten', 'fireworks']))
    dump(WORK/'pilot.json', answers)
    for answer in answers:
        print(json.dumps({'pilot_provider': answer['provider'], 'accepted': answer['accepted'],
                          'correct': score(dataset[0], answer), 'latency_ms': answer['latency_ms'],
                          'usage': answer['calls'][0]['usage'] if answer['calls'] else {},
                          'failure': answer.get('failure')}), flush=True)
    if any(answer.get('failure') == 'transport' for answer in answers):
        raise SystemExit('Pilot transport failure. Full benchmark not started; inspect sanitized diagnostic before retrying.')
    return answers


def run(dataset):
    require_historical_backend()
    pilot_path = WORK/'pilot.json'
    if not pilot_path.exists() or any(r.get('failure') == 'transport' for r in json.loads(pilot_path.read_text())):
        raise SystemExit('A successful connectivity pilot is required first.')
    run_dir = WORK/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run_dir.mkdir(parents=True)
    before = preserved_files()
    metadata = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'baseline_git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'harness_sha256': digest(Path(__file__)), 'dataset_sha256': digest(WORK/'cases.json'),
                'pricing': PRICING, 'case_count': len(dataset), 'repetitions': 3,
                'max_concurrent_trials': 2, 'max_concurrent_provider_requests': 4,
                'temperature': .1, 'max_tokens': 2048, 'per_provider_socket_timeout_sec': 45,
                'notes': ['Identical production extraction prompt captured without a network call.',
                          'Two concurrent trials: results reflect light benchmark load, not isolated single-request latency.',
                          'Parallel agreement deliberately waits for both providers. No production race or cancellation is tested.',
                          'First-valid time is observational and excludes production race coordination/cancellation.',
                          'Safe rejection is a fail-closed outcome, not proof that a useful clarification question was generated.',
                          'Expected answers are agent-authored from explicit synthetic instructions; no user/domain-expert signoff.',
                          'No SAM, nesting, G-code generation, real inventory or file-upload HTTP endpoint is exercised.',
                          'Cost is an estimate from reported tokens and public list prices, not grant-account billing.']}
    dump(run_dir/'metadata.json', metadata)
    dump(run_dir/'cases.json', dataset)
    dump(run_dir/'fixtures.json', json.loads((WORK/'fixtures.json').read_text()))
    jobs = [(c, rep, mode) for c in dataset for rep in range(1, 4)
            for mode in ['current_failover', 'parallel_agreement']]
    random.Random(20261029).shuffle(jobs)
    records = []
    def trial(job):
        c, rep, mode = job
        answer = baseline(c) if mode == 'current_failover' else parallel(c)
        return {'case_id': c['id'], 'repetition': rep, 'mode': mode,
                'expected_action': c['expected_action'], **answer, 'correct': score(c, answer)}
    print(f'RUN_DIRECTORY={run_dir}', flush=True)
    with (run_dir/'trials.jsonl').open('w', encoding='utf-8') as output, ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(trial, job) for job in jobs]
        for future in as_completed(futures):
            record = future.result()
            output.write(json.dumps(record, ensure_ascii=False)+'\n')
            output.flush()
            records.append(record)
            print(json.dumps({'completed': len(records), 'total': len(jobs), 'case': record['case_id'],
                              'mode': record['mode'], 'accepted': record['accepted'],
                              'correct': record['correct'], 'latency_ms': record['latency_ms']}), flush=True)
            dump(run_dir/'progress.json', {'completed': len(records), 'total': len(jobs), 'summary': summarize(records)})
    metadata['finished_utc'] = datetime.now(timezone.utc).isoformat()
    metadata['protected_files_unchanged'] = before == preserved_files()
    dump(run_dir/'metadata.json', metadata)
    summary = summarize(records)
    dump(run_dir/'summary.json', summary)
    print(json.dumps({'finished': True, 'protected_files_unchanged': metadata['protected_files_unchanged'], 'summary': summary}), flush=True)


def require_historical_backend():
    """Do not compare today's guarded parser with the old unguarded parallel mode."""
    baseline = 'e231b084d3fa6474e078cbe22423a6576563bdbd'
    for name in ('backend/m2_spark_orchestrator.py', 'backend/llm_client.py', 'backend/materials.py'):
        original = subprocess.check_output(['git', 'show', baseline + ':' + name], cwd=ROOT)
        current = (ROOT/name).read_bytes()
        if original.replace(b'\r\n', b'\n') != current.replace(b'\r\n', b'\n'):
            raise SystemExit('Historical comparison requires the original backend revision. Current parsing/repair has changed; applying its guards to only one mode would be unfair. --prepare and report rendering remain offline.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--pilot', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    dataset = prepare()
    if args.pilot:
        pilot(dataset)
    if args.run:
        run(dataset)
