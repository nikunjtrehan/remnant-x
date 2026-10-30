# Frontend validation · 30 October 2026

## Automated checks

- `npm run check`: **41 frontend tests passed**, followed by TypeScript and
  Vite production build. The suite includes actual IndexedDB file round trips,
  immutable review approval/retry, rejected-review recovery, StrictMode draft
  hydration, retained workspace mode, stale export blocking and preservation of
  material edits after removing the selected photo.
- Full offline backend suite: **184 passed in 70.15 seconds**. The eight new
  review-workflow tests cover approval eligibility, replay-safe acceptance,
  physical-ID collisions, rejected/cropped review refusal, restart recovery,
  exact-plan confirmation without renesting, stale batch rollback, location
  integrity, duplicate photo refusal and stale-plan reporting.
- One existing Starlette/httpx deprecation warning remains.
- Dependency installation audit: zero known vulnerabilities. The new
  `fake-indexeddb` package is a development-only test dependency.

## Current factory browser exercise

The UI used an isolated origin/port, database and artifacts under
`.task-tmp/factory-qa`. Perception was explicitly replaced with local-threshold
geometry in an ignored test harness; order-provider calls were disabled. Marker
calibration, vectorization, durable reviews, inventory writes, DXF loading,
nesting, final program verification and saved-plan confirmation used real code.

| Scenario | Observed outcome |
| --- | --- |
| Three photos in one ZIP | Two valid captures and one missing-marker rejection; the other photos were retained |
| Marker 2 missing | Bottom-right corner named, highlighted red, analysis disabled, replacement/setup actions visible |
| Analyze two ready photos | Two pending geometry reviews, two perception calls, zero available inventory records |
| Refresh before acceptance | Original photos and pending reviews restored; perception count remained two |
| Visual acceptance | Checkbox required before acceptance; stock became available only after accepting geometry |
| Review recovered through Inventory | Second pending review opened and accepted without another perception call |
| Physical IDs and locations | Two stable IDs saved; location edited and the printable SVG contained the saved ID, grade, thickness, current location and test-stock marking |
| Vendor DXF plus “make 50 copies” | Actual deterministic fallback produced quantity 50; 50/50 nested and software verified |
| Refresh a verified job | Live view, job quantity, uploaded-file references and stable plan ID restored; saved result recovered without renesting |
| Operator-reported completion | Explicit declaration required; exact saved plan updated predicted stock atomically |
| Another worker changes stock | A separate test transaction changed the selected sheet; subsequent export and completion were both blocked and the plan labelled outdated |
| Replan against current stock | A fresh valid plan completed the browser download event for its verified program |
| Laptop layout | 1024 × 768 checked without horizontal document overflow; temporary viewport restored after testing |

Browser testing exposed a development StrictMode hydration bug. Persistence now
waits for the restored state to commit; a regression runs the same remount
behaviour. No empty draft overwrites the stored job.

## Separate live physical API exercise

The [two-piece report](../docs/architecture/PHYSICAL_VALIDATION_20261030.md)
records eight actual station photographs: five successful real SAM contours,
two calibration rejections before SAM and one clipped-mask topology rejection.
The unmodified contours produced a real Baseten-parsed 50-copy DXF job and a
complete nine-part job across both sheets, with final software verification.
These were isolated API checks, not a second browser exercise. Physical source
photos remain private. Corrected references were supplied after results; exterior
errors reach 7.32 mm. The user corrected the remaining gap reference to 80 mm;
the detected gaps are 80.54 and 81.36 mm.

The live captures also prompted clearer recapture guidance for calibration
failure and disconnected contours, including a single sheet cropped by the
station boundary. Geometry thresholds and model output were not changed.

## Earlier milestone evidence retained

The preceding frontend milestones exercised 101 distinct uploaded DXFs, a
separate 50-copy upload order, partial results, explicit demo seeding, per-sheet
downloads, planned-path playback and the recorded guided example. Those checks
are functional evidence, not a throughput benchmark or a claim of optimal
packing. The older desktop replan-and-commit action has been replaced by the
saved-plan confirmation flow above.

## Scope and limits

- No new live SAM accuracy or paid provider test was performed in this exercise.
  The public example is synthetic/local-threshold; physical test photos remain
  private.
- Glare, blur, occlusion, overlap and flatness require the documented visual
  checks. Automatic dimensional or image-quality certification is not claimed.
- Browser recovery requires available storage and the same origin. Clearing
  browser data removes unsent files. Completed backend reviews remain recoverable
  from the same database; interrupted computations are not durable worker jobs.
- No active-call cancellation, factory-wide sheet reservation, public deployment,
  authentication or machine telemetry is added by this milestone.
- The legacy direct API auto-save/commit contracts remain available to trusted
  callers. The desktop uses explicit review and exact-plan confirmation.
- Verified program geometry and predicted remaining stock do not certify
  physical dimensions, process qualification, achieved cut quality or savings.

See [FACTORY_SCENARIOS.md](FACTORY_SCENARIOS.md) for the operating matrix and
[WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md) for API/recovery semantics.
