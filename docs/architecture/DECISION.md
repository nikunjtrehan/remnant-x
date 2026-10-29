# ADR 006: Order interpretation provider strategy

Status: Provisional decision after initial benchmark

Published baseline produced 50/60 correct outcomes at a 3.23-second median; parallel agreement produced 51/60 at 18.73 seconds. Historical decision: keep primary-first routing provisionally and prioritize explicit missing-input and contradiction checks before changing the default provider policy. The parallel agreement policy remains experimental; this benchmark does not justify enabling an automatic race. Parallel agreement caught some errors, so retain it as a candidate review mode; its measured delay and blocked complete orders count against making it mandatory.

## Context

At the baseline revision, Remnant X used Baseten-first sequential provider failover for natural-language
order interpretation. An earlier three-cloud blackboard was removed as unused code.
That cleanup did not establish that sequential execution outperforms parallel execution.
The product still needs evidence for any replacement policy.

## Experiment

120 / 120 trials · 20 prompts · 3 repetitions per mode. Fifteen prompts define complete orders; five contain absent,
undecided, conflicting or impossible requirements. Expectations were written from
the prompts before network requests and have not had independent domain-expert review.
The parallel policy requires both providers to pass existing validation and agree
on normalized manufacturing requirements. Both use the same Muse Spark Open model
family with provider defaults unchanged. This is not a test of independent model
families, a specialized auditor, or a production speculative race.

Baseline application commit: `e231b084d3fa6474e078cbe22423a6576563bdbd`.
Dataset SHA-256: `29572e558859ceb166986687003bbbb4f91b3efc68fa89926a3de3b661566b55`.
Detailed aggregate results and case outcomes: [benchmark.json](benchmark.json).
Readable static page: [index.html](index.html).
Reproduction: [benchmark instructions](../../benchmarks/README.md).

## Outcomes

```json
{
  "current_failover": {
    "trials": 60,
    "correct_outcomes": 50,
    "correct_accepts": 44,
    "wrong_accepts": 9,
    "unnecessary_blocks": 1,
    "safe_rejections": 6,
    "incomplete_transport": 0,
    "median_ms": 3225.62,
    "p95_ms": 6748.59,
    "provider_requests": 60,
    "successful_provider_requests": 60,
    "reported_prompt_tokens": 28944,
    "reported_completion_tokens": 57522,
    "estimated_known_usd": 0.261641,
    "requests_without_cost_estimate": 0,
    "estimated_usd_per_correct_accept": 0.005946
  },
  "parallel_agreement": {
    "trials": 60,
    "correct_outcomes": 51,
    "correct_accepts": 42,
    "wrong_accepts": 6,
    "unnecessary_blocks": 3,
    "safe_rejections": 9,
    "incomplete_transport": 1,
    "median_ms": 18729.57,
    "p95_ms": 31498.0,
    "provider_requests": 120,
    "successful_provider_requests": 119,
    "reported_prompt_tokens": 57347,
    "reported_completion_tokens": 109687,
    "estimated_known_usd": 0.491953,
    "requests_without_cost_estimate": 1,
    "estimated_usd_per_correct_accept": 0.011713,
    "observed_first_valid_median_ms": 3091.4
  }
}
```

The observed median first-valid time among parallel trials with a valid candidate
was **3.09 s**. This is not the latency of a deployed race; coordination,
cancellation, loser billing and behavior after a late disagreement remain untested.

Selecting the first schema-valid candidate from the recorded parallel responses
would yield 50/60 correct outcomes,
10 wrong acceptances and 45
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

- Identical production extraction prompt captured without a network call.
- Two concurrent trials: results reflect light benchmark load, not isolated single-request latency.
- Parallel agreement deliberately waits for both providers. No production race or cancellation is tested.
- First-valid time is observational and excludes production race coordination/cancellation.
- Safe rejection is a fail-closed outcome, not proof that a useful clarification question was generated.
- Expected answers are agent-authored from explicit synthetic instructions; no user/domain-expert signoff.
- No SAM, nesting, G-code generation, real inventory or file-upload HTTP endpoint is exercised.
- Cost is an estimate from reported tokens and public list prices, not grant-account billing.

Application Python files, real `.env` and `warehouse.db`: hashes verified unchanged.
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
