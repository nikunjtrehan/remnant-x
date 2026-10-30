# Desktop integration and publication review

30 October 2026. Scope: the local desktop prototype, repository presentation and
publication preparation. Public hosting and physical machine operation are separate.

## Current checks

| Check | Result |
| --- | --- |
| Full offline backend suite | 184 passed in 49.14 s |
| Frontend interaction/unit suite | 42 passed across 11 files; final run 24.00 s |
| TypeScript and Vite production build | Passed; 335.28 kB JS, 106.31 kB gzip |
| npm dependency audit | Zero reported vulnerabilities |
| Existing warning | Starlette/httpx test-client deprecation |
| New GitHub Checks workflow | Prepared for Windows, Python 3.11 and Node 22; hosted execution awaits publication |

Local validation used Windows, Python 3.11 and Node 25.2.1. The first backend
attempt encountered a missing parent directory for its test-output path.
Creating that directory resolved the setup failure; no backend code changed.

## Real browser-to-backend exercise

The actual React application connected to the actual FastAPI app with a separate
SQLite database and artifacts under an ignored local validation directory.
No perception or order-provider implementation was replaced.

The private ZIP contained original photographs of A, B and B with a covered
marker. These are two physical pieces, not three inventory sheets. Ground-truth
hole measurements were never entered into the application.

| Step | Observed result |
| --- | --- |
| Import ZIP | Three original photographs retained with per-photo fields |
| Check all photos | A/B ready; covered marker ID 2 blocked with targeted guidance |
| Analyze ready photos | Two real Meta SAM 3.1 results: one L hole for A, two holes and an exterior notch for B |
| Refresh before acceptance | Original files and both completed reviews recovered without another indexing request |
| Visual acceptance | Checkbox required; exactly two stock identities accepted, with cardboard/3 mm metadata and locations |
| Vendor upload | Generated, millimetre-unit 20 × 15 mm closed-polyline DXF imported through the UI |
| Natural-language order | Real Baseten Muse Spark Open returned quantity 50 and the uploaded-part binding; observed provider latency 3.47 s |
| Nest and verify | 50/50 placed on B; final program passed verification |
| Export | Browser download completed after current-stock checking |
| Refresh and recover plan | Saved fifty-copy plan recovered without another parse/nesting request |
| Restart API | The nine-part saved plan and both accepted stock records remained recoverable |
| Second natural-language job | Nine 120 × 50 mm rectangles placed across both sheets: seven on A, two on B; both programs verified |
| Independent geometry checks | Placements covered by extracted stock; no pairwise area overlap or intersection with existing holes |
| Stock after previews/download | Both stored geometries and material metadata unchanged; no completion receipt recorded |
| Configuration/production data | Private hashes confirmed `.env` and production DB files unchanged |

The structured execution requests took 0.97 s for fifty DXF parts and 0.44 s for
the nine-part job. Those times exclude the separately requested cloud order
interpretation. They are individual observations, not latency guarantees.
The earlier [physical experiment](architecture/PHYSICAL_VALIDATION_20261030.md)
retains its own frozen masks, measurements and timings; these additional browser
runs do not replace it.

## Small presentation changes

- Photo overlays use a bright exterior outline and distinct cyan hole outlines,
  with a matching legend. The millimetre geometry and model masks are unchanged.
- Accepted captures retain their saved-photo overlay, allowing later inspection
  without another segmentation call. Toggling Photo preserved the exact SVG paths.
- The example explains that no API is needed. Actual backend outages remain
  visible in Live workspace. This distinction is covered by the new regression.
- Provenance labels render `meta_sam_3.1` as Meta SAM 3.1 without changing stored
  source values. Synthetic example stock has a descriptive label instead of a
  missing physical-location warning.
- The README uses an actual synthetic-example screenshot and separates quick
  trial, live setup and detailed engineering contracts.

The recorded example also loaded in the browser with the API deliberately
stopped. It remained a recorded example and did not substitute for a live request.

## Publication boundary

Private photographs, model-response streams, experimental databases, local test
harnesses, credentials, dependencies, build output and private handoff notes stay
excluded. The README screenshot contains only our synthetic recorded example.
The matching review/plan API changes from earlier local milestones must publish
with the frontend; publishing only the browser folder would omit required contracts.

The [winner README/hosting review](REPOSITORY_PRESENTATION_RESEARCH.md) records
sources, inspected commits and uncertainty about submission-time hosting.
No Meta-authored “best README” rule or custom-domain requirement was verified.
No domain purchase or public deployment was performed.

The existing frontend milestones remain separate local commits. The final work
is prepared for user review before the requested GitHub push. CI configuration
is not represented as a successful hosted CI run.

## Practical limits

This validates a supervised cardboard-photo demonstration and local software
workflow. It does not qualify metal/glare segmentation, uniform dimensional
accuracy, dimensional kerf compensation, workholding or an actual machine process.
The physical report records exterior errors up to 7.32 mm and post-result
reference corrections. Saved-plan completion remains an operator declaration;
no physical cutting was performed during this exercise.
