# Desktop workbench milestones

The frontend lives here; FastAPI remains the only backend. Local milestone commits
are review checkpoints. Publishing to GitHub is a separate step.

| Milestone         | Deliverable                                                                                               | Acceptance                                                                                                  |
| ----------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| 1 · Workbench     | React/TypeScript/Vite shell; SVG geometry workspace; explicit example/live modes                          | Production build; viewer coordinate and selection tests                                                     |
| 2 · Capture       | Station profile, photo preflight, marker overlays, SAM indexing and inventory                             | Missing markers block analysis; changed inputs invalidate preflight; no preflight model/DB writes           |
| 3 · Manufacturing | Prompt review, multi-DXF tray, batch nesting, verification, downloads and explicit predicted-stock update | Real API contract; partial/unsafe outputs cannot masquerade as a complete job; stale UI results invalidated |
| 4 · Demonstration | Backend-generated synthetic example; guided visual replay; accessible interactions and browser checks     | Replay stays separate from live work; browser-tested photo failures and actual offline batch execution      |

## Design decisions

- A quiet, light industrial workbench with a dark navigation rail and green geometry.
  The sheet is the focal point; operational details sit beside it.
- SVG draws the backend's already positioned millimetre polygons. One Y-axis
  conversion, holes preserved, no second placement engine in the browser.
- Curated examples and replay adopt the researched presentation patterns. Live
  requests show elapsed time; their outcomes come from the API.
- Ordinary components, one typed API module, CSS and React state. No additional
  backend, UI agent framework or 3D renderer.
- The existing backend re-plans on an inventory-update request. The UI must call
  that action “Replan & update stock”, explain it, then show the returned plan.
  It must not claim to commit exactly the previously displayed layout.
- Indexing is explicitly “Analyze & add to inventory”: one model run, one saved
  result. Reviewing an unsaved scan and saving that exact artifact needs a separate
  backend contract and is not implied by this button.
- Private physical photographs stay outside the frontend. The public example uses
  a reproducibly generated synthetic station and real backend results.

## Validation record

Results are added after each milestone passes its checks.

### Milestone 1

- Geometry tests cover the single Y-axis conversion, retained holes, dimensions,
  keyboard selection and viewer zoom reset.
- TypeScript and the production Vite build pass.
- Dependencies were checked at installation; patched Vitest 4 replaced an older
  test runner flagged by npm audit. The resolved installation reports zero known
  vulnerabilities. Dependency versions are recorded in `package-lock.json`.

### Milestone 2

- Added one read-only photo-preflight route using the existing ArUco/calibration
  implementation, with marker coordinates, actionable issues and rectified frame.
- Seven API tests pass: all four missing-marker cases still fail real indexing;
  valid preflight writes no database/files and calls no segmentation; bad station
  dimensions fail; managed DXF downloads cannot expose non-DXF files.
- Scanner tests exercise automatic checks, changed-profile invalidation and
  retained input after segmentation failure. Inventory can inspect actual stock
  and explicitly seed demo stock after a reset explanation.
- No provider calls, private-photo publication or production-inventory changes
  are needed to verify this milestone.

### Milestone 3

- Prompt parsing has an editable structured review; vendor uploads keep per-file
  errors and bind accepted files to explicit quantities without another model.
- Per-sheet geometry, controller settings, final verification, G-code/result
  downloads and predicted stock updates are connected to FastAPI.
- Ten frontend checks pass, including exact grade retention, invalidating old
  results after editing, partial-batch handling and upload-to-50 binding.
- Browser validation used a separate `.task-tmp/frontend-dev` database: explicitly
  loaded three demo sheets, planned eight rectangles through the actual endpoint,
  saw 8/8 software-verified placements, then completed the explained replan/update
  action. The application showed the newly returned result and updated stock.
- No production warehouse changes or paid inference were used for these checks.

### Milestone 4

- Added a reproducible backend-generated recording for 28 parts on one synthetic
  L-cutout sheet, with source/hash/timing provenance. Its measured occupation is
  44.45%; this is not a measured improvement over another nesting baseline.
- Added a guided four-chapter walkthrough, explicit example/live modes, planned
  toolpath playback and rectified-image SAM box selection. Live drafts remain
  separate from example state; they survive mode/navigation changes in the page.
- Split order/request logic from cutting-plan inspection so each is readable.
  Source is formatted; generated coordinates remain compact data, not hand code.
- **16 frontend tests pass**, including mode isolation, walkthrough skipping,
  selected-sheet downloads, missing markers, exact grades, partial/invalid batches,
  stale-input invalidation and box coordinates. TypeScript and production build pass.
- **174 offline backend tests pass**. Actual browser checks include eight-part
  stock update, 50 copies of one vendor DXF, 101 distinct definitions with 101/101
  verified placements, real marker rejection/pass, region selection and playback.
- See `VALIDATION.md` for the observed checks, development-reload rerun and limits.
  No private photograph, production database or provider credential is included.
