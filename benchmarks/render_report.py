"""Render reviewed benchmark evidence into a local static architecture page."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys

from dotenv import dotenv_values
from benchmarks.order_interpretation import ROOT, WORK, canonical, summarize, score
from backend.db_and_parts import CADPartFactory


def clean(value):
    text = json.dumps(value, ensure_ascii=False)
    for key, secret in dotenv_values(ROOT/'.env').items():
        if any(term in key.upper() for term in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')) and secret and len(secret) > 8:
            text = text.replace(secret, '[REDACTED]')
    text = text.replace(str(ROOT).replace('\\', '\\\\'), '<project>')
    return json.loads(text)


def compact_fixture(source, target):
    """Publish equivalent CAD geometry without thousands of unused DXF table tags."""
    poly = CADPartFactory.load_part_from_dxf(str(source))
    tags = ['0', 'SECTION', '2', 'HEADER', '9', '$ACADVER', '1', 'AC1015',
            '9', '$INSUNITS', '70', '4', '0', 'ENDSEC', '0', 'SECTION', '2', 'ENTITIES']
    for ring in [poly.exterior, *poly.interiors]:
        points = list(ring.coords)[:-1]
        tags += ['0', 'LWPOLYLINE', '100', 'AcDbEntity', '8', '0', '100', 'AcDbPolyline',
                 '90', str(len(points)), '70', '1']
        for x, y in points:
            tags += ['10', str(x), '20', str(y)]
    target.write_text('\n'.join(tags + ['0', 'ENDSEC', '0', 'EOF']) + '\n', encoding='ascii')
    assert CADPartFactory.load_part_from_dxf(str(target)).equals(poly)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def render(run_dir):
    metadata = json.loads((run_dir/'metadata.json').read_text(encoding='utf-8'))
    cases = json.loads((run_dir/'cases.json').read_text(encoding='utf-8'))
    fixtures = json.loads((run_dir/'fixtures.json').read_text(encoding='utf-8'))
    records = [json.loads(line) for line in (run_dir/'trials.jsonl').read_text(encoding='utf-8').splitlines()]
    summary = summarize(records)
    finished = bool(metadata.get('finished_utc')) and len(records) == 120
    by_id = {c['id']: c for c in cases}
    first_valid = []
    for r in records:
        if r['mode'] != 'parallel_agreement':
            continue
        valid = [candidate for candidate in r['provider_results'] if candidate['accepted']]
        winner = min(valid, key=lambda candidate: candidate['latency_ms']) if valid else {
            'accepted': False, 'failure': r.get('failure')}
        first_valid.append({'case_id': r['case_id'], 'repetition': r['repetition'],
                            'accepted': winner['accepted'], 'winner': winner.get('provider'),
                            'correct': score(by_id[r['case_id']], winner)})
    first_analysis = {'status': 'observational_only_not_a_deployed_race', 'trials': len(first_valid),
                      'correct_outcomes': sum(r['correct'] for r in first_valid),
                      'wrong_accepts': sum(r['accepted'] and not r['correct'] for r in first_valid),
                      'correct_accepts': sum(r['accepted'] and r['correct'] for r in first_valid),
                      'selections': first_valid}
    public_rows = []
    for record in records:
        keep = {key: record[key] for key in ['case_id', 'repetition', 'mode', 'expected_action', 'accepted',
                'correct', 'latency_ms', 'failure', 'spec', 'observed_first_valid_ms'] if key in record}
        keep['providers'] = [{key: r[key] for key in ['provider', 'accepted', 'latency_ms', 'failure', 'spec'] if key in r}
                             for r in record.get('provider_results', [])]
        keep['usage'] = [{'provider': call['provider'], 'requested_model': call['model'],
                          'ok': call['ok'], 'latency_ms': call['latency_ms'],
                          'usage': call['usage'], 'estimated_usd': call['estimated_usd']}
                         for call in record['calls']]
        public_rows.append(keep)
    report = clean({'status': 'complete' if finished else 'in_progress', 'completed': len(records),
                    'total': 120, 'started_utc': metadata['started_utc'],
                    'finished_utc': metadata.get('finished_utc'),
                    'baseline_commit': metadata['baseline_git_commit'],
                    'dataset_sha256': metadata['dataset_sha256'],
                    'harness_sha256': metadata['harness_sha256'],
                    'protected_files_unchanged': metadata.get('protected_files_unchanged'),
                    'pricing': metadata['pricing'], 'method_notes': metadata['notes'],
                    'fixtures': fixtures, 'cases': cases, 'summary': summary,
                    'observed_first_valid_policy': first_analysis, 'trials': public_rows})
    pilot_rows = json.loads((WORK/'pilot.json').read_text(encoding='utf-8'))
    report['pilot'] = [{key: row[key] for key in ['provider', 'accepted', 'latency_ms']} |
                       {'usage': row['calls'][0]['usage'],
                        'estimated_usd': row['calls'][0]['estimated_usd']} for row in pilot_rows]
    report['usage_accounting'] = {
        'provider_requests_including_pilot': sum(s['provider_requests'] for s in summary.values()) + len(pilot_rows),
        'known_estimated_usd_including_pilot': round(sum(s['estimated_known_usd'] for s in summary.values()) +
            sum(row['estimated_usd'] or 0 for row in report['pilot']), 6),
        'requests_with_unknown_cost': sum(s['requests_without_cost_estimate'] for s in summary.values())}
    output = ROOT/'docs'/'architecture'
    output.mkdir(parents=True, exist_ok=True)
    (output/'fixtures').mkdir(exist_ok=True)
    shutil.copyfile(run_dir/'cases.json', output/'cases.json')
    for fixture in fixtures:
        fixture['download_sha256'] = compact_fixture(WORK/'uploads'/fixture['name'], output/'fixtures'/fixture['name'])
        fixture['download_note'] = 'Equivalent minimal DXF; sha256 retains the original experimental file hash.'
    report['fixtures'] = clean(fixtures)
    archive = gzip.compress(json.dumps(report, ensure_ascii=False).encode(), mtime=0)
    (output/'benchmark-full.json.gz').write_bytes(archive)
    public = {key: value for key, value in report.items() if key not in {'trials', 'cases', 'observed_first_valid_policy'}}
    public['case_definitions'] = 'cases.json'
    public['observed_first_valid_policy'] = {key: value for key, value in first_analysis.items() if key != 'selections'}
    public['trials'] = [{key: row[key] for key in ('case_id', 'repetition', 'mode', 'accepted', 'correct', 'latency_ms', 'failure') if key in row} for row in public_rows]
    public['full_evidence_archive'] = {'path': 'benchmark-full.json.gz', 'sha256': hashlib.sha256(archive).hexdigest(),
                                      'note': 'Full normalized trial/provider/usage evidence, preserved without duplication in the page.'}
    assert json.loads(gzip.decompress(archive)) == report
    (output/'benchmark.json').write_text(json.dumps(public, indent=2, ensure_ascii=False), encoding='utf-8')
    baseline = summary.get('current_failover', {})
    parallel = summary.get('parallel_agreement', {})
    decision = 'Evidence collection is still running; no routing decision is supported yet.'
    if finished:
        decision = (f"Published baseline produced {baseline['correct_outcomes']}/60 correct outcomes at a "
                    f"{baseline['median_ms']/1000:.2f}-second median; parallel agreement produced "
                    f"{parallel['correct_outcomes']}/60 at {parallel['median_ms']/1000:.2f} seconds. "
                    'Historical decision: keep primary-first routing provisionally and prioritize explicit missing-input '
                    'and contradiction checks before changing the default provider policy. The parallel agreement '
                    'policy remains experimental; this benchmark does not justify enabling an automatic race.')
        if parallel.get('wrong_accepts', 0) < baseline.get('wrong_accepts', 0):
            decision += ' Parallel agreement caught some errors, so retain it as a candidate review mode; its measured delay and blocked complete orders count against making it mandatory.'
    label = lambda mode: 'Published baseline' if mode == 'current_failover' else 'Parallel agreement'
    percent = lambda n, d: f'{n}/{d} ({100*n/d:.1f}%)' if d else '—'
    modes = ['current_failover', 'parallel_agreement']
    metric_rows = [
        ('Correct outcomes', lambda s: percent(s['correct_outcomes'], s['trials'])),
        ('Correct complete orders accepted', lambda s: str(s['correct_accepts'])),
        ('Incorrect orders accepted', lambda s: str(s['wrong_accepts'])),
        ('Complete orders blocked', lambda s: str(s['unnecessary_blocks'])),
        ('Incomplete / invalid orders safely rejected', lambda s: str(s['safe_rejections'])),
        ('Transport-incomplete trials', lambda s: str(s['incomplete_transport'])),
        ('Median response', lambda s: f"{s['median_ms']/1000:.2f} s"),
        ('P95 response', lambda s: f"{s['p95_ms']/1000:.2f} s"),
        ('Provider requests', lambda s: str(s['provider_requests'])),
        ('Reported input / output tokens', lambda s: f"{s['reported_prompt_tokens']:,} / {s['reported_completion_tokens']:,}"),
        ('Estimated known list-price cost', lambda s: f"${s['estimated_known_usd']:.4f}"),
        ('Requests with unknown cost', lambda s: str(s['requests_without_cost_estimate'])),
    ]
    rows = ''.join('<tr><th scope="row">'+html.escape(name)+'</th>'+''.join(
        '<td>'+html.escape(fn(summary[mode]) if mode in summary else 'Pending')+'</td>' for mode in modes)+'</tr>'
        for name, fn in metric_rows)
    grouped = defaultdict(list)
    for r in records:
        grouped[r['case_id']].append(r)
    case_html = ''
    for c in cases:
        outcome = []
        for mode in modes:
            items = [r for r in grouped[c['id']] if r['mode'] == mode]
            outcome.append(f'{sum(r["correct"] for r in items)}/{len(items)} correct' if items else 'Pending')
        expected = canonical(c['expected']) if c['expected'] else {'expected_action': 'reject_or_clarify', 'reason': c['rationale']}
        observations = [r for r in public_rows if r['case_id'] == c['id']]
        trial_rows = ''.join(f'<tr><td>{label(r["mode"])}</td><td>{r["repetition"]}</td><td>{r["accepted"]}</td><td>{r["correct"]}</td><td>{r["latency_ms"]/1000:.2f}s</td></tr>' for r in observations)
        wrong = sorted({json.dumps(r.get('spec'), sort_keys=True) for r in observations if r['accepted'] and not r['correct']})
        errors = '<h4>Distinct incorrect accepted specifications</h4><pre>' + html.escape('\n'.join(wrong)) + '</pre>' if wrong else ''
        case_html += f'''<details class="case" data-action="{c['expected_action']}"><summary><span>{html.escape(c['id'].replace('_',' '))}</span><span class="case-scores">{outcome[0]} · {outcome[1]}</span></summary><p>{html.escape(c['prompt'])}</p><p class="muted">Expected: {html.escape(c['expected_action'].replace('_',' '))}. {html.escape(c['rationale'])}</p><h4>Expected requirements</h4><pre>{html.escape(json.dumps(expected, indent=2))}</pre><div class="table-scroll"><table><thead><tr><th>Mode</th><th>Run</th><th>Accepted</th><th>Correct</th><th>Time</th></tr></thead><tbody>{trial_rows}</tbody></table></div>{errors}</details>'''
    metadata_line = f"{len(records)} / 120 trials · 20 prompts · 3 repetitions per mode"
    status = 'Completed experiment' if finished else 'Experiment in progress'
    first_valid = parallel.get('observed_first_valid_median_ms')
    first_text = f'{first_valid/1000:.2f} s' if first_valid is not None else 'Pending'
    notes_html = ''.join('<li>'+html.escape(note)+'</li>' for note in metadata['notes'])
    body = TEMPLATE.replace('@@STATUS@@', status).replace('@@META@@', metadata_line)
    body = body.replace('@@DECISION@@', html.escape(decision)).replace('@@ROWS@@', rows)
    body = body.replace('@@CASES@@', case_html).replace('@@FIRST@@', first_text).replace('@@NOTES@@', notes_html)
    body = body.replace('@@COMMIT@@', metadata['baseline_git_commit']).replace('@@DATAHASH@@', metadata['dataset_sha256'])
    body = body.replace('@@UNCHANGED@@', 'Verified unchanged after the run.' if metadata.get('protected_files_unchanged') else 'Final preservation check pending.')
    body = body.replace('@@STAMP@@', html.escape(metadata.get('finished_utc') or metadata['started_utc']))
    body = body.replace('@@FIXTURES@@', '<div class="links"><a href="fixtures/rectangle_40x30.dxf" download>Download rectangle DXF</a><a href="fixtures/plate_60x40_hole_20x10.dxf" download>Download plate-with-hole DXF</a><a href="cases.json" download>Download frozen test cases</a></div>')
    findings = ''
    if finished:
        findings = ('<div class="aside"><strong>The main gap is intent validation.</strong> '
                    'In the historical baseline, both modes accepted all three missing-thickness trials and all three explicitly undecided-quantity trials. '
                    'Baseline parsing also silently reversed the impossible ring dimensions once. '
                    'Parallel checking reduced wrong acceptances from 9 to 6, while blocking three complete orders instead of one. '
                    'All 60 baseline provider calls succeeded at the API level; provider failover itself was not exercised.</div>')
        findings += (f'<p class="subtle">Selecting the first schema-valid candidate from the recorded parallel responses '
                     f'would have yielded {first_analysis["correct_outcomes"]}/60 correct outcomes and '
                     f'{first_analysis["wrong_accepts"]} wrong acceptances. This is an observational selection analysis, '
                     'not an executed race or an estimate of cancellation costs.</p>')
    body = body.replace('@@FINDINGS@@', findings)
    decisions = json.loads((output/'original-decisions.json').read_text(encoding='utf-8'))
    founding = '<section id="founding"><h2>Project decisions and current evidence</h2><p>The comparison above describes the published baseline. Later changes have separate evidence.</p><div class="links"><a href="APPLICATION_PROMISE_AUDIT.md">Application promises</a><a href="PHYSICAL_VALIDATION.md">Physical ground truth protocol</a><a href="REPOSITORY_AUDIT.md">Repository and winner review</a><a href="intent-validation.json">20-case follow-up validation snapshot</a><a href="benchmark-full.json.gz" download>Full historical trial archive (gzip)</a><a href="original-decisions.json">Full decision rationale and evidence links</a></div>'
    for item in decisions:
        founding += '<article class="record"><span class="tag">'+html.escape(item['id'])+'</span><div><h3>'+html.escape(item['title'])+'</h3><p>'+html.escape(item['choice'])+'</p><p class="subtle">'+html.escape(item['status'])+'</p></div></article>'
    body = body.replace('</main>', founding + '</section></main>')
    (output/'index.html').write_text(body, encoding='utf-8')
    (output/'DECISION.md').write_text(f'''# ADR 006: Order interpretation provider strategy

Status: {'Provisional decision after initial benchmark' if finished else 'Evidence collection in progress'}

{decision}

## Context

At the baseline revision, Remnant X used Baseten-first sequential provider failover for natural-language
order interpretation. An earlier three-cloud blackboard was removed as unused code.
That cleanup did not establish that sequential execution outperforms parallel execution.
The product still needs evidence for any replacement policy.

## Experiment

{metadata_line}. Fifteen prompts define complete orders; five contain absent,
undecided, conflicting or impossible requirements. Expectations were written from
the prompts before network requests and have not had independent domain-expert review.
The parallel policy requires both providers to pass existing validation and agree
on normalized manufacturing requirements. Both use the same Muse Spark Open model
family with provider defaults unchanged. This is not a test of independent model
families, a specialized auditor, or a production speculative race.

Baseline application commit: `{metadata['baseline_git_commit']}`.
Dataset SHA-256: `{metadata['dataset_sha256']}`.
Detailed aggregate results and case outcomes: [benchmark.json](benchmark.json).
Readable static page: [index.html](index.html).
Reproduction: [benchmark instructions](../../benchmarks/README.md).

## Outcomes

```json
{json.dumps(summary, indent=2)}
```

The observed median first-valid time among parallel trials with a valid candidate
was **{first_text}**. This is not the latency of a deployed race; coordination,
cancellation, loser billing and behavior after a late disagreement remain untested.

Selecting the first schema-valid candidate from the recorded parallel responses
would yield {first_analysis['correct_outcomes']}/{first_analysis['trials']} correct outcomes,
{first_analysis['wrong_accepts']} wrong acceptances and {first_analysis['correct_accepts']}
correct complete orders. This is a descriptive selection analysis, not a third
live execution mode. It does not establish a causal improvement over the separate
baseline runs.

## Important findings

- Both modes accepted all three missing-thickness cases and all three undecided-quantity cases.
- Baseline parsing accepted two missing-diameter cases and reversed impossible ring dimensions once.
- Parallel agreement rejected those three additional invalid interpretations, but blocked three complete orders instead of one.
- One parallel block was a Fireworks timeout; two were missing/invalid structured responses from one provider.
- All 60 baseline provider requests succeeded at the API level, so failover recovery was not exercised.
- The small synthetic test set and repeated prompts do not establish universal accuracy or statistical superiority.
- Model agreement cannot replace checking explicit customer requirements. A valid toolpath can still cut a misunderstood part.

These findings motivate a clarification/intent gate shared by all provider modes,
followed by another frozen evaluation. The application has not been changed by
this benchmark. Retaining its routing provisionally is not an endorsement of
unreviewed ambiguous orders.

## Fixture provenance

Both DXFs were generated locally with the existing CAD exporter, using millimeter
closed straight polylines, then checked with the actual loader for polygon equality.
The rectangle is 40 x 30 mm (1,200 mm2). The plate is 60 x 40 mm with a
20 x 10 mm rectangular hole (2,200 mm2 solid area). No third-party vendor files
were downloaded. Paths were supplied as uploaded-file context; HTTP upload was
not part of this experiment.

## Limitations and integrity

{chr(10).join('- '+note for note in metadata['notes'])}

Application Python files, real `.env` and `warehouse.db`: {'hashes verified unchanged' if metadata.get('protected_files_unchanged') else 'final check pending'}.
The pilot used two additional provider requests and is excluded from the 120 trials.
The published result excludes raw reasoning text, credentials and local absolute paths.
This decision record is ready to incorporate into the planned static architecture website.
This preserves historical baseline evidence; later implementation is documented separately below.

## Follow-up evidence

This record describes the original 120-trial experiment, not today's routing implementation.
The separately dated [20-case follow-up](intent-validation.json) recorded 20/20
correct outcomes after input guards; it is not a repeat of the comparison.
The current [application audit](APPLICATION_PROMISE_AUDIT.md) and
[repository review](REPOSITORY_AUDIT.md) describe subsequent implementation changes.
Full normalized trial details remain downloadable in [the gzip archive](benchmark-full.json.gz).
The downloadable minimal DXFs preserve the original geometry; metadata records
both the original experimental byte hash and the compact download hash.
''', encoding='utf-8')
    print(json.dumps({'output': str(output), 'status': report['status'], 'completed': len(records), 'summary': summary}))


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Remnant X — Engineering Decisions</title><meta name="description" content="Architecture decisions, measured provider comparisons, and the evidence behind Remnant X."><style>
:root{--ink:#172d31;--paper:#f6f5ef;--muted:#586b6c;--line:#d4dcd5;--teal:#12695d;--lime:#daeac7;--orange:#bd4b2e}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}a{color:var(--teal);text-underline-offset:4px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:3px solid var(--orange);outline-offset:5px}.wrap{max-width:1160px;margin:auto;padding:0 40px}header{border-bottom:1px solid var(--line)}.nav{display:flex;align-items:center;justify-content:space-between;min-height:82px;gap:25px}.brand{font-size:20px;font-weight:800;letter-spacing:-.8px;text-decoration:none;color:var(--ink)}.brand span{color:var(--teal)}nav{display:flex;gap:28px;font-size:13px}nav a{color:var(--muted);text-decoration:none}.hero{padding:72px 0 52px;display:grid;grid-template-columns:1fr 280px;gap:45px;align-items:center}.eyebrow{font:700 11px/1.5 ui-monospace,monospace;letter-spacing:2px;text-transform:uppercase;color:var(--teal);margin:0 0 20px}h1{font-size:clamp(38px,5.5vw,65px);line-height:1.05;letter-spacing:-3px;margin:0 0 24px;max-width:740px;font-weight:650}h1 em{font-style:normal;color:var(--teal)}.lede{max-width:650px;color:var(--muted);font-size:18px}.sheet{width:100%;max-width:280px;opacity:.9}.status{display:inline-flex;gap:8px;align-items:center;background:var(--lime);padding:7px 12px;font:600 11px ui-monospace,monospace}.status:before{content:"";width:6px;height:6px;background:var(--teal);border-radius:100%}.meta{font:12px/1.7 ui-monospace,monospace;color:var(--muted)}section{padding:44px 0;border-top:1px solid var(--line);scroll-margin-top:20px}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:22px}h2{font-size:29px;letter-spacing:-1px;line-height:1.2;margin:0 0 22px}h3{font-size:18px;line-height:1.4;letter-spacing:-.3px;margin:0 0 8px}h4{font-size:12px;text-transform:uppercase;letter-spacing:1px}.decision{border-left:4px solid var(--teal);background:#e9eee3;padding:24px 28px;margin-top:20px}.decision p{margin:6px 0}.tag{font:600 10px ui-monospace,monospace;text-transform:uppercase;letter-spacing:1px;color:var(--teal)}.table-scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:13px 16px;text-align:left;border-bottom:1px solid var(--line)}thead th{font:600 11px ui-monospace,monospace;text-transform:uppercase;letter-spacing:.6px;background:#e9eee3}tbody th{font-weight:450}td{font-variant-numeric:tabular-nums}td:nth-child(3){background:#eaf0e7}.subtle{font-size:13px;color:var(--muted)}.aside{padding:18px 22px;border:1px solid var(--line);margin:22px 0;font-size:14px}.aside strong{color:var(--orange)}.columns{display:grid;grid-template-columns:1fr 1fr;gap:36px}.method-step{display:flex;gap:18px;margin-bottom:20px}.number{flex-shrink:0;font:500 11px ui-monospace,monospace;color:var(--teal);padding-top:4px}.method-step p{margin:0;font-size:14px;color:var(--muted)}.record{display:grid;grid-template-columns:90px 1fr;gap:20px;padding:25px 0;border-bottom:1px solid var(--line)}.record p{margin:6px 0;color:var(--muted);font-size:14px}.record .tag{padding-top:4px}.tools{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}button{font:500 12px system-ui;border:1px solid var(--line);background:transparent;color:var(--ink);padding:8px 13px;cursor:pointer}button[aria-pressed="true"]{background:var(--ink);color:white;border-color:var(--ink)}.case{border-top:1px solid var(--line);padding:14px 0}.case:last-child{border-bottom:1px solid var(--line)}summary{cursor:pointer;display:flex;justify-content:space-between;gap:20px;list-style:none;font-size:14px;font-weight:600}summary:before{content:"+";color:var(--teal);width:12px;flex-shrink:0}details[open] summary:before{content:"−"}summary span:first-of-type{flex:1;text-transform:capitalize}.case-scores{font:11px/1.8 ui-monospace,monospace;font-weight:400;color:var(--muted)}pre{background:#eaece5;padding:18px;overflow:auto;font:12px/1.6 ui-monospace,monospace;border:1px solid var(--line);white-space:pre-wrap;overflow-wrap:anywhere}.muted{color:var(--muted)}.notes{padding-left:20px;font-size:14px;color:var(--muted)}.notes li{padding:4px 0}.links{display:flex;flex-wrap:wrap;gap:24px;font-size:13px}footer{background:var(--ink);color:#e3eadc;padding:30px 0;margin-top:35px}footer p{margin:0;font-size:12px}.hash{overflow-wrap:anywhere;font-size:11px}svg text{font:10px ui-monospace,monospace;fill:var(--muted)}@media(max-width:760px){.wrap{padding:0 22px}.hero{padding:45px 0 30px;grid-template-columns:1fr}.sheet{display:none}h1{letter-spacing:-1.5px}.nav{align-items:flex-start;padding:22px 0;gap:16px;flex-direction:column}nav{gap:20px;font-size:12px}.columns{grid-template-columns:1fr;gap:12px}.section-head{display:block}.record{grid-template-columns:65px 1fr;gap:12px}summary{flex-wrap:wrap;gap:8px}.case-scores{width:100%;padding-left:24px}th,td{padding:12px 9px;min-width:130px}.decision{padding:18px}section{padding:32px 0}}
</style></head><body><header><div class="wrap nav"><a class="brand" href="#">REMNANT <span>X</span></a><nav aria-label="Main navigation"><a href="#benchmark">Benchmark</a><a href="#decisions">Decisions</a><a href="#evidence">Evidence</a><a href="#limits">Limitations</a></nav></div></header><main class="wrap">
<div class="hero"><div><p class="eyebrow">Engineering record / 29 October 2026</p><h1>Decisions backed<br>by <em>evidence.</em></h1><p class="lede">Why Remnant X works the way it does. Measured tradeoffs, explicit boundaries, and the tests behind our manufacturing workflow.</p><span class="status">@@STATUS@@</span><p class="meta">@@META@@</p></div><svg class="sheet" viewBox="0 0 280 260" role="img" aria-label="Illustration of parts nested on a remnant sheet; not benchmark geometry"><path d="M24 28H256V232H24Z" fill="#daeac7" stroke="#12695d" stroke-width="1.5"/><path d="M24 28L85 28L85 60L24 60Z" fill="#f6f5ef" stroke="#12695d"/><circle cx="141" cy="102" r="35" fill="#f6f5ef" stroke="#12695d"/><circle cx="141" cy="102" r="14" fill="#daeac7" stroke="#12695d"/><path d="M37 84H86V137H37Z M37 150H115V212H37Z M130 158H163V212H130Z M183 46H237V142H183Z M183 158H237V212H183Z" fill="#f6f5ef" stroke="#12695d"/><path d="M24 14H256 M24 10V18 M256 10V18" stroke="#586b6c"/><text x="98" y="9">PLAN → VERIFY</text><text x="34" y="250">ILLUSTRATIVE NESTING / NOT TO SCALE</text></svg></div>
<section id="benchmark"><div class="section-head"><h2>01 / Provider comparison</h2><span class="meta">Same requirements. Different execution policies.</span></div><p>Published baseline asks Baseten first and uses existing fallback behavior. Parallel agreement asks Baseten and Fireworks independently, then accepts only matching, validated manufacturing requirements. Both hosts use the Muse Spark Open family.</p><div class="table-scroll"><table><thead><tr><th scope="col">Measured outcome</th><th scope="col">Published baseline</th><th scope="col">Parallel agreement</th></tr></thead><tbody>@@ROWS@@</tbody></table></div><div class="aside"><strong>A race has not been deployed.</strong> Observed median first-valid time in parallel trials: <b>@@FIRST@@</b>. Returning early, cancellation, late disagreement, and loser billing require a separate implementation and evaluation.</div>@@FINDINGS@@<div class="decision"><span class="tag">ADR 006 / Provisional routing decision</span><p>@@DECISION@@</p></div></section>
<section id="method"><h2>02 / How the comparison works</h2><div class="columns"><div><div class="method-step"><span class="number">01</span><div><h3>Fix expectations before the calls</h3><p>15 complete orders and five incomplete, undecided, conflicting or impossible instructions. Expected outcomes are derived from explicit synthetic instructions; no model judges the answers.</p></div></div><div class="method-step"><span class="number">02</span><div><h3>Use the production extraction prompt</h3><p>Same schema, temperature 0.1 and 2,048-token limit. Run each prompt three times per policy, in a fixed shuffled order. Maximum two simultaneous trials / four provider calls.</p></div></div></div><div><div class="method-step"><span class="number">03</span><div><h3>Compare manufacturing requirements</h3><p>Grade, thickness, kerf, quantities, dimensions, grain restrictions and DXF binding matter. Generated IDs do not. Equivalent unlocked rotations and grouped identical items are normalized.</p></div></div><div class="method-step"><span class="number">04</span><div><h3>Preserve the application</h3><p>No SAM requests, nesting, machine output or inventory transactions. Backend Python, real configuration and warehouse database hashes are checked before and after. @@UNCHANGED@@</p></div></div></div></div><h3>Where the DXFs come from</h3><p class="subtle">Generated locally with the existing exporter, then checked for exact polygon equality using the actual loader. Closed straight polylines, millimeter units, no downloaded vendor files. Paths are supplied as upload context; this experiment does not exercise HTTP upload.</p><div class="table-scroll"><table><thead><tr><th>Fixture</th><th>Dimensions</th><th>Solid area</th></tr></thead><tbody><tr><th>Rectangle</th><td>40 × 30 mm</td><td>1,200 mm²</td></tr><tr><th>Plate with rectangular hole</th><td>60 × 40 mm; hole 20 × 10 mm</td><td>2,200 mm²</td></tr></tbody></table></div>@@FIXTURES@@</section>
<section id="decisions"><h2>03 / Architecture decision log</h2><article class="record"><span class="tag">ADR 001</span><div><h3>Models interpret; geometry verifies</h3><p>Models supply segmentation and order interpretation. Local geometry determines placement; a deterministic compiler emits a bounded toolpath. Model confidence is not a substitute for checking the final program.</p><p><b>Tradeoff:</b> a valid toolpath can still describe a misunderstood order. Explicit intent checks and user review remain necessary.</p></div></article><article class="record"><span class="tag">ADR 002</span><div><h3>Verify the complete batch, then commit once</h3><p>Every used sheet must pass final-program verification before one SQLite transaction changes inventory. Stale geometry, material, thickness or provenance rejects the update; partial orders cannot commit.</p><p><b>Boundary:</b> inventory records predicted post-cut stock. The API does not execute a machine or confirm a physical cut.</p></div></article><article class="record"><span class="tag">ADR 003</span><div><h3>Real SAM, explicit local demonstrations</h3><p>Meta SAM 3.1 provides the segmentation mask. Local thresholding is a separately selected demonstration mode with persistent provenance. Lighting normalization remains opt-in.</p><p><b>Boundary:</b> synthetic geometry and mask transport tests do not establish physical camera accuracy. Measured station acceptance remains pending.</p></div></article><article class="record"><span class="tag">ADR 004</span><div><h3>Material grades remain distinct</h3><p>SS304 and SS316, or AL6061 and AL5052, cannot silently substitute for each other. Explicit recognized prompt grades are checked against the interpreted order.</p><p><b>Tradeoff:</b> conservative identities avoid substitutions but do not provide a comprehensive alloy-equivalence database.</p></div></article><article class="record"><span class="tag">ADR 005</span><div><h3>Bounded CAD and controller contracts</h3><p>DXF import supports one planar closed straight-polyline boundary and disjoint holes. Prepared controller emitters target bounded GRBL 1.1 and LinuxCNC laser configurations, with optional checked arc lead-ins. Unsupported geometry and commands fail clearly.</p><p><b>Boundary:</b> no arbitrary vendor DXF, proprietary controller, dimensional kerf compensation, or real-machine qualification is claimed.</p></div></article><article class="record"><span class="tag">ADR 006</span><div><h3>Choose provider policy from observed behavior</h3><p>Removing unused blackboard functions simplified the running path but did not demonstrate that parallel execution was worse. This experiment records latency, correct outcomes, wrong acceptance, blocked orders and token usage.</p><p><b>Boundary:</b> two deployments of the same model family can agree on the same mistake. Agreement does not prove intent or physical safety.</p></div></article><article class="record"><span class="tag">ADR 007</span><div><h3>Keep demo stock explicit</h3><p>Startup does not seed inventory. Synthetic and local-threshold stock retain source provenance and require an explicit opt-in during order execution. A separate demo database can be selected.</p><p><b>Reason:</b> demonstration material must not silently become real warehouse availability.</p></div></article><article class="record"><span class="tag">ADR 008</span><div><h3>Measure timings; leave unsupported savings unset</h3><p>Stage durations, quantities, usable area and utilization are measured. Money and carbon savings stay unset until equivalent-production baselines, prices and lifecycle assumptions exist.</p><p><b>Reason:</b> packing utilization alone does not establish financial or environmental savings.</p></div></article><article class="record"><span class="tag">ADR 009</span><div><h3>Keep the backend easy to trace</h3><p>HTTP routes delegate manufacturing orchestration to one pipeline module. Shared schemas describe requests; serialization converts geometry and results to API data. The nester uses NFP contact placement and seeded parallel simulated annealing.</p><p><b>Tradeoff:</b> clear local responsibilities and compatibility aliases support development, but do not provide global nesting optimality, distributed scheduling or a production job system.</p></div></article></section>
<section id="evidence"><div class="section-head"><h2>04 / Inspect the cases</h2><span class="meta">Expand a case to see expected and observed outcomes.</span></div><div class="tools" aria-label="Filter cases"><button type="button" data-filter="all" aria-pressed="true">All 20 cases</button><button type="button" data-filter="accept" aria-pressed="false">Complete orders</button><button type="button" data-filter="reject_or_clarify" aria-pressed="false">Reject or clarify</button></div>@@CASES@@</section>
<section id="limits"><h2>05 / What the evidence does not establish</h2><ul class="notes">@@NOTES@@</ul><p class="subtle">The two-request connectivity pilot is excluded from the 120-trial totals. Public model pricing was checked on 29 October 2026: $1.25 input, $0.15 cached input, $4.25 output per million tokens on each host. Estimates use reported usage, not account invoices or grant deductions.</p><div class="links"><a href="https://www.baseten.co/library/muse-spark-open/">Baseten pricing</a><a href="https://fireworks.ai/models/fireworks/muse-spark-open">Fireworks pricing</a><a href="benchmark.json" download>Download reviewed results</a><a href="DECISION.md">Decision record</a><a href="https://github.com/nikunjtrehan/remnant-x/tree/@@COMMIT@@">Baseline source</a></div><p class="meta hash">Baseline commit: @@COMMIT@@<br>Dataset SHA-256: @@DATAHASH@@<br>Evidence timestamp (UTC): @@STAMP@@</p></section></main><footer><div class="wrap"><p>REMNANT X / An engineering record. Observed results are separated from proposed behavior.</p></div></footer><script>
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-filter]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));document.querySelectorAll('.case').forEach(item=>{item.hidden=button.dataset.filter!=='all'&&item.dataset.action!==button.dataset.filter;});}));
</script></body></html>'''


if __name__ == '__main__':
    directory = Path(sys.argv[1]) if len(sys.argv)>1 else sorted(p for p in WORK.iterdir() if p.is_dir() and (p/'metadata.json').exists())[-1]
    render(directory)
