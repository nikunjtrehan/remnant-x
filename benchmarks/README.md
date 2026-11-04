# Order interpretation comparison

## Reproduce the published evidence without API keys

From the repository root after installing `requirements-dev.txt`:

```powershell
.\.venv\Scripts\python.exe -m benchmarks.order_interpretation --prepare
.\.venv\Scripts\python.exe -m benchmarks.replay_report
```

Preparation validates the 20 authored cases and two generated DXF fixtures.
Replay reads the public `docs/architecture/benchmark-full.json.gz`, checks all
120 case/mode/repetition records, recomputes historical correctness and summary
statistics, and verifies the public fixture hashes and geometry. No model calls,
private run directory or inventory writes are needed. Optional
`--output .task-tmp/benchmark-replay.json` writes a new report and refuses to
overwrite an existing file.

This reproduces the **historical observations and scoring**, not a new measurement
of the current parser. The production parser has changed since that experiment.

## Opt-in live comparison

This is an opt-in live evaluation, separate from the application. It does not
run nesting, emit G-code, write warehouse inventory, or exercise the HTTP upload
endpoint. Running it uses configured provider credits.

```powershell
.\.venv\Scripts\python.exe -B -m benchmarks.order_interpretation --prepare
.\.venv\Scripts\python.exe -B -m benchmarks.order_interpretation --pilot
.\.venv\Scripts\python.exe -B -m benchmarks.order_interpretation --run
```

The offline preparation freezes 20 synthetic prompts with expected outcomes:
15 complete orders and five instructions that should be rejected or clarified.
Expected answers are authored from the instructions, not judged by another
language model. They have not been independently approved by a domain expert.

Two locally generated DXFs use millimeters and straight closed LWPOLYLINEs:

| Fixture | Bounds | Solid area | Holes |
| --- | --- | --- | --- |
| Rectangle | 40 x 30 mm | 1,200 mm2 | 0 |
| Plate with rectangular hole | 60 x 40 mm | 2,200 mm2 | One, 20 x 10 mm |

The actual DXF loader must reproduce the intended polygons before live calls.
The benchmark supplies these paths as uploaded-part context; it does not claim
to measure vendor CAD compatibility or the browser/file-upload workflow.

Each case runs three times through the production failover parser and three
times through an experimental parallel agreement policy. The parallel policy
independently extracts the same full order on Baseten and Fireworks, then
accepts only when both pass the existing structural, material and DXF checks
and agree on normalized manufacturing requirements. It is not a specialized
metallurgy model, a production speculative race, or an independent safety
certificate. Both providers are configured to use the same model family.

The extraction prompt, temperature 0.1, and 2,048-token limit matched the published
baseline when the historical comparison ran. Current parsing adds input guards
and bounded repair. Live comparison commands now refuse a changed backend, since
applying those guards to only one mode would make the comparison unfair. Offline
preparation and offline replay of the preserved historical run remain available.
The sequential mode in that experiment retained failover and regex fallback.
Generated part/order IDs are ignored; identical items are merged when comparing
quantities, and unlocked rectangle/bracket rotations are equivalent. Grain locks,
grades, thickness, kerf, dimensions, quantities and fixture binding are scored.

The 120 trials normally make 180 model requests, plus two pilot requests.
Failover can make additional requests. Trial order uses a fixed shuffled seed.
Two trials can run simultaneously (at most four provider calls), so latency
reflects light benchmark load rather than isolated single-user performance.
The socket timeout matches production at 45 seconds per provider; this is not
a strict whole-request deadline. Ordinary cached model prefixes are not disabled.

Raw results, the frozen dataset, fixture hashes, metadata and progress are saved
under ignored `.task-tmp/order-benchmark/`. Do not publish raw artifacts without
review. Provider errors and raw output can contain environment-specific paths.
The report distinguishes safe rejection from generating a useful clarification.
Transport outages do not count as correct clarification. First-valid latency is
observational; it does not demonstrate a working cancellation-aware race.

Cost estimates use reported usage and public list prices checked on 29 October
2026: $1.25 input, $0.15 cached input and $4.25 output per million tokens for
Muse Spark Open on both hosts. Missing usage or other providers remain unknown.
These estimates do not establish actual grant deductions or invoice charges.

- [Baseten published model pricing](https://www.baseten.co/library/muse-spark-open/)
- [Fireworks published model pricing](https://fireworks.ai/models/fireworks/muse-spark-open)

The resulting architecture decision belongs in the static decision website.
Keep observations, alternatives, chosen policy, rationale and limitations together;
do not label a parallel agreement experiment as a deployed production feature.

## Maintainer-only site publishing

`python -m benchmarks.render_report <run-directory>` regenerates the static
decision site and tracked evidence files. It requires the original private
`metadata.json`, `trials.jsonl` and pilot records, which are intentionally absent
from a public clone. It is not the contributor verification command; use
`benchmarks.replay_report` above. `--help` describes the required input.

The readable page shows compact case tables; complete normalized provider/spec/
usage evidence is retained in `docs/architecture/benchmark-full.json.gz`. Download
fixtures use an equivalent minimal DXF representation, with both byte hashes
recorded. The raw private run remains unchanged under `.task-tmp/`.
