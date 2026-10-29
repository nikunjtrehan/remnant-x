# Frontend validation · 30 October 2026

## Automated checks

- `npm run check`: **16 frontend tests passed**, followed by TypeScript and Vite production build.
- Complete offline Python suite: **174 passed in 68.81 seconds**. Seven new API
  checks cover preflight, all four missing-marker cases, unchanged indexing
  rejection, calibration failures and managed DXF download boundaries. One
  existing Starlette/httpx deprecation warning remains.
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
| Desktop layout | 1024 × 768 viewport tested without horizontal document overflow; viewport override reset afterward |

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
- Live drafts are session UI state. They survive navigation/mode switches, not
  page reloads. Server-side recovery is outside this milestone.
- Desktop/laptop is the intended initial surface. Mobile capture, authentication,
  public deployment and machine qualification are outside this local prototype.
- Software verification and the occupation percentage are the backend's planned
  geometry checks/metrics. They do not certify physical dimensions, achieved cut
  quality, financial savings or CO₂ savings.
