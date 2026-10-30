# Repository audit and winner-source review

29 October 2026. Scope: backend, tests, evaluation tooling and architectural evidence.
This backend milestone added no frontend or machine connection. The subsequent
[desktop integration review](../FINAL_READINESS.md) records the completed UI,
current tests and two-piece physical follow-up. No winner code was copied or executed.

## What the public winner sources actually show

These are inspected public snapshots, which may include changes after the contests.
They are not reconstructions of the exact versions the judges ran, and the sample
does not establish a causal formula for winning.

| Project and verification | Backend files inspected | Useful observation |
| --- | --- | --- |
| OrgLens, first prize in Meta's [announcement](https://www.linkedin.com/posts/meta-for-developers_were-excited-to-announce-the-winners-of-activity-7325596881483354112-Kvt5) | [Django views](https://github.com/TheCl3m/llama-hack/blob/c07af10f61a50e2e12b8600b3492504f952eb8ab/backend/api/views.py), models, URL configuration and `create_summaries.py` at the same revision | Ordinary models and a direct streaming endpoint; heavier summaries are prepared separately in parallel. Reuse frameworks for routine work and keep model roles identifiable. |
| CrossBeam, first place in [Anthropic's announcement](https://claude.com/resources/articles/meet-the-winners-of-our-built-with-opus-4-6-claude-code-hackathon) | [Server entry](https://github.com/mikeOnBreeze/cc-crossbeam/blob/cc5591e7e824ba5cafa9b8c6507258b996aac011/server/src/index.ts), extract/generate routes, extraction service, corrections-analysis flow and file verification utility | Thin HTTP entry points delegate work to named flows with explicit outputs. Its external services and domain research are workload-specific, not infrastructure every project should copy. |
| Elisa, second place in the same Anthropic announcement | [Agent runner](https://github.com/zoidbergclawd/elisa/blob/10f7880a603af1e61f2737cffaeffbf6b159b620/backend/src/services/agentRunner.ts) and orchestrator at the same revision | Explicit limits, cancellation and separate planning/execution/testing phases. It is a larger system; its size is not a target for a geometry application. |

The observations above are our architectural inferences from the source, not claims
about the judges' private reasoning. Anthropic also describes Elisa as a substantial
AI-assisted codebase; the evidence does not support treating a line-count threshold
or AI authorship as a disqualifier.

For Google, the official [Gaze Link engineering account](https://android-developers.googleblog.com/2024/11/gaze-link-wins-best-android-app-gemini-api-developer-competition.html)
describes ML Kit plus Gemini, while the official [Trippy account](https://firebase.blog/posts/2024/11/gemini-competition-best-firebase-app)
describes Firebase Functions and several managed services. This review did not find
and inspect an authenticated public source repository for those exact projects;
their internals must not be presented as source-audited. Their documented division
of responsibilities is useful context, not a template to copy wholesale.

## Audit decisions for Remnant X

- Keep one FastAPI application, one manufacturing pipeline and one local inventory.
  No agent framework, service mesh, distributed queue or cloud geometry service.
- Keep SAM responsible for segmentation, models responsible for interpreting
  requests, and ordinary code responsible for numeric geometry and verification.
- Consolidate NFP placement and annealing into the existing nesting module. Remove
  the separate search wrapper and superseded grid implementation. Compatibility
  names all point to the same implementation.
- Replace the new miniature Python interpreter with a restricted emitter contract:
  one bounded loop over numeric blocks, simple formatting, no imports, general calls,
  mutable job access or arbitrary attribute access. Prepared, checked-in emitters
  carry source hashes and are independently checked on every emitted job.
- Keep Muse Code on the preparation path. The real CLI generated the two shipped
  emitters; end users do not install or call a coding agent to execute each job.
- Put complete machine-readable benchmark detail in a separate gzip archive and
  show readable case tables instead of repeated JSON dumps. Retain original private
  experiment files. Regenerate compact downloadable DXFs and verify polygon equality;
  preserve the experimental and download hashes separately.
- Keep the historical routing comparison historical. Its live harness now refuses
  modified parser code, preventing an unfair comparison with guards in only one mode.

## Baseten, Fireworks and Meta: bounded jobs

| Service | Implemented role | Boundary |
| --- | --- | --- |
| Meta SAM 3.1 | Actual segmentation masks for photo indexing | Does not establish material, thickness or physical accuracy by itself. |
| Baseten Muse Spark Open | Default natural-language order extraction | Requirements must pass the source-intent and structured validation gates. |
| Fireworks Muse Spark Open | Existing transport failover plus one repair of a rejected complete-order extraction | Original missing/contradictory inputs stop before any model. Repair cannot change the requested grade, dimensions, quantity or kerf. No repeated agent debate. |
| Meta Muse Spark 1.3 | Supported direct parsing alternative through `REMNANTX_ORDER_PROVIDER=meta` | The model interprets filter requirements; local SQL and geometry remain authoritative. No claim that a million-token warehouse prompt is necessary. |
| Muse Code | Offline preparation of actual GRBL and LinuxCNC emitter functions | Generated code must satisfy the narrow contract and probes; final job output is checked again. |

Parallel work is useful when tasks are independent. The backend runs bounded NFP
search chains in parallel for mixed shapes; it avoids duplicate chains when all
instances have the same geometry or annealing is disabled. Separate stock captures
and future order preparation can also overlap at the caller. Mandatory duplicate
order inference was not justified by the historical experiment.

Further candidate uses for Fireworks include reviewing an exception batch or
summarizing deterministic failure reasons for an operator. These are suggestions,
not implemented features or safety decisions. Neither provider should invent
machine settings, authorize a cut or certify a physical mask.

## Live evidence for the new provider role

One live normal order passed Baseten parsing in 3,715.74 ms. A separate controlled
test injected an invalid primary extraction with quantity six instead of five;
real Fireworks returned a corrected extraction in 7,347.21 ms, and the independent
requirements check accepted quantity five. The fixture is not evidence that Baseten
made that error. These two live calls are a connectivity/repair demonstration, not
a new accuracy benchmark or latency guarantee. `.env` and real inventory hashes
were unchanged. Unit tests also reject a still-wrong repair and prevent further retries.

A separate live request using the supported direct Meta option returned the correct
order from Muse Spark 1.3 in 4,832.25 ms without a repair. These single observations
do not establish which provider is faster or more accurate.

## Findings fixed during implementation

- Rotation deduplication now compares geometry, not rounded bounds/centroids.
- The independent placement check includes stock-edge clearance.
- Duplicate ArUco station IDs fail before homography.
- Photo indexing requires supplied material and thickness rather than inventing steel/3mm.
- Final G-code verification binds arc direction, contour order, configured feed,
  power and dwell; it requires an explicit laser-off state before rapid travel.
- Requested arc lead-ins must fit in waste, clear of other parts and stock holes.
  Their cut footprints and kerf are included in predicted inventory, transformed
  back from machine-origin coordinates to the stock's original frame.
- LinuxCNC output establishes exact-path mode and uses M2 program end. Unsupported
  proprietary controller requests still fail explicitly.
- The first physical capture exposed unnecessary NFP triangulation products for
  concave obstacles and rings. The existing hole-area containment bound now applies
  to concave shells too, without changing their contours or raising budgets.
- Tangent lead-ins no longer require a polygon chord longer than the arc diameter;
  dense circle/ring contours use the existing independent clearance checks.

One old lifecycle test assumed a particular first-job packing would leave room
for two future discs on one sheet. On the new residual geometry, both the old grid
and NFP placed only one. The revised test requires reuse of that stock plus valid
spillover, and still checks avoidance of the first job's cuts. It does not promise
that an unknown future order fits a particular leftover sheet.

## Limits that remain

The [first physical capture](PHYSICAL_VALIDATION_20261029.md) passed calibrated
indexing with one piece and one L-shaped hole, followed by isolated workflow tests.
Exterior dimension errors reach 4.7 mm. Physical remeasurement corrected the
original hole-offset notes to 73/69 mm top/left; baseline extraction is
73.46/68.65 mm without adjustment. Overall physical acceptance and repeatability
across captures remain unproven.
No numerical solver proves a photograph matches reality. NFP calculations use GEOS
double precision, conservative polygonal clearance and explicit complexity budgets;
annealing is a bounded heuristic. Arc checks use a stated sampling envelope.
No thermal, workholding, cutter-compensation or physical machine process has been
qualified. No model-driven correction of actual manufacturing feedback is claimed.
Current test evidence and the precise application mapping are maintained in the
[application audit](APPLICATION_PROMISE_AUDIT.md).
