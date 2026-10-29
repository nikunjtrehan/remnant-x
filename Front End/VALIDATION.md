# Frontend validation · 30 October 2026

## Automated checks

- `npm run check`: **29 frontend tests passed**, followed by TypeScript and Vite production build.
- Complete offline Python suite: **176 passed in 85.58 seconds**. Seven earlier API
  checks cover preflight, all four missing-marker cases, unchanged indexing
  rejection, calibration failures and managed DXF download boundaries. One
  existing Starlette/httpx deprecation warning remains.
- Two additional API regressions prove the uploaded-DXF “make 50 copies” wording
  and the existing “cut 50 of” wording preserve quantity, material grade and file
  binding when the cloud is unavailable.
- Dependency audit at installation: zero known vulnerabilities after upgrading
  the test runner to patched Vitest 4.1.12. Resolved versions are in the lockfile.

## Browser checks against the real API

The API ran with a separate database and artifact directory under
`.task-tmp/frontend-dev`. No production warehouse, environment file, private
physical photo or provider credit was used for these checks.

| Scenario | Observed outcome |
| --- | --- |
| Explicit demo seeding | Confirmation explains the reset; three tagged demo sheets loaded |
| Structured order: eight rectangles | 8/8 placed, verified program, preview did not update stock |
| Predicted-stock action | Replan explanation shown; atomic update returned and newly planned result displayed |
| Photo missing marker 2 | Actual 3/4 detections, marker location/retake guidance, analysis blocked |
| Complete synthetic station at its matching dimensions | 4/4 detected; calibration check passed; rectified preview shown |
| Optional SAM region | Dragged box produced a region prompt in the rectified frame |
| Upload one DXF, quantity 50 | 50/50 placed and verified; browser downloaded the actual `.nc` program |
| 101 distinct DXFs, one instance each | Imported through the production UI with bounded concurrency; 101/101 placed and software verified; preview remained non-mutating |
| Planned toolpath playback | Active point rendered; pause and reset controls worked; playback labeled separately from a live machine |
| Guided example | Source image, extracted hole, placements and verified path can be stepped through; complete result is accessible without waiting |
| Desktop layout | Batch UI checked at 1024 × 768 and 1440 × 900 without horizontal document overflow; viewport override reset afterward |
| ZIP photo intake | Three synthetic station photos imported; real calibration accepted two and blocked the missing-marker image; offline perception saved the two valid sheets independently |
| Repeated ZIP import | The same archive imported again produced three duplicate notices and kept the queue at three photos |
| DXF plus a prompt | “Make 50 copies of the uploaded DXF from 3 mm steel sheet, kerf 1 mm” parsed through the real offline fallback; 50/50 parts nested and verified |

The ZIP save test used `.task-tmp/frontend-upgrade/offline_api.py`: a private
test-only API replacing perception with explicit local-threshold geometry and
disabling model requests. It used a separate database and never changes the
production API implementation. Frontend regressions additionally cover SHA-256
duplicate-image rejection, import/expansion limits, material requirements,
per-file partial success, completed-photo repeat prevention, stop-after-current,
shared station settings, multi-field calibration editing without losing the open
setup panel, and pre-analysis inventory-ID collisions. This is not a
live multi-photo SAM accuracy or provider-throughput test.

A development-server restart interrupted an earlier large-batch viewing session.
The 101-file flow was repeated on the stable production preview and its final
101/101 verified state was observed in the browser. This is functional evidence,
not a latency benchmark or a claim of globally optimal placement.

## Scope and limits

- The real SAM UI request is wired to the existing indexing endpoint. This build
  used mocked inference in interaction tests and the previously validated backend
  transport/geometry suite; no new paid end-to-end SAM or order-provider call was
  made during frontend construction.
- The public recording is explicitly **synthetic / local_threshold**, not a SAM
  accuracy experiment. The original physical photographs remain private.
- Stage events and cancellation do not exist in the API. Live requests show an
  activity indicator and actual elapsed time, followed by the real result/error.
- The stock-update API re-plans; the UI explains that contract. A future
  exact-preview commit needs a stable backend plan identifier and stale rejection.
- Live drafts and photo batches are session UI state. They survive navigation/mode switches, not
  page reloads. Server-side recovery is outside this milestone.
- Desktop/laptop is the intended initial surface. Mobile capture, authentication,
  public deployment and machine qualification are outside this local prototype.
- Software verification and the occupation percentage are the backend's planned
  geometry checks/metrics. They do not certify physical dimensions, achieved cut
  quality, financial savings or CO₂ savings.
