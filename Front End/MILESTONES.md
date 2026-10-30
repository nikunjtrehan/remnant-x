# Desktop workbench milestones

The frontend lives here; FastAPI remains the only backend. Milestone commits
are review checkpoints, preserved in the published GitHub history.

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

### Milestone 5 · Batch intake and usability review

- Added loose-photo and browser-side ZIP intake, a thumbnail/status queue, shared
  station calibration, batch defaults and per-photo overrides. Import limits are
  50 photos, 20 MB per image and 100 MB total. Exact duplicate bytes are skipped.
- Calibration gates each photo; only ready photos with explicit material/thickness
  can reach analysis. Existing inventory-ID collisions block analysis. Successful
  sheets save independently; blocked/failed photos stay visible. Stopping waits
  for the current request and does not pretend to cancel it.
- Improved the upload-plus-prompt instructions, stock-import entry, initial result
  summary, field sizes and secondary-text contrast while retaining the original
  geometry workspace and recorded walkthrough.
- Fixed the bounded offline DXF quantity rule for “50 copies of the uploaded DXF”.
  Material/intent checks and the multiple-upload clarification boundary remain.
- **29 frontend tests, 176 offline backend tests, TypeScript and production build
  pass.** Browser checks imported three synthetic photos from a ZIP (two accepted,
  one missing-marker rejection) and saved the accepted pair through a private
  offline perception harness. A DXF prompt produced a 50/50 verified cutting plan.
- Public workflow semantics and limitations are in `WORKFLOW_GUIDE.md`; subjective
  ratings remain in private local notes. No paid batch inference or publication
  was performed.

### Milestone 6 · Durable backend reviews and exact plans

- Two tables in the existing SQLite database retain immutable optical reviews
  and complete verified cut plans. No additional backend service is introduced.
- Reviewed analysis stays outside usable inventory until explicit acceptance.
  Stable IDs recover completed work; acceptance cannot overwrite physical stock.
- Current-stock checks flag outdated plans. Exact-plan confirmation applies saved
  footprints and its replay receipt in the same transaction, without renesting.
- Location metadata survives cuts and disconnected-island records.
- **184 offline backend tests pass**, including the eight review-workflow cases.

### Milestone 7 · Factory-facing review, recovery and identification

- Missing-marker corners are named and highlighted, calibration problems have
  distinct guidance, and failed photos have targeted replacement/setup actions.
- Photo/geometry overlays, zoom and explicit visual acceptance cover outline and
  hole inspection. The border guard blocks a truncated outline.
- Physical stock IDs, rack/slot editing and printable labels connect inventory
  selection to the sheet a worker retrieves.
- IndexedDB preserves original photos; local storage preserves job drafts and
  views. Backend reviews/receipts reconcile completed work without automatic AI
  retries. StrictMode hydration and removal of a selected batch photo are covered.
- Program download checks current stock. Operator completion uses the exact
  stored plan; downloads and physical completion are separate states.
- **41 frontend tests, TypeScript and production build pass.** The isolated
  browser exercise covered the factory scenarios recorded in VALIDATION.md.
- The earlier desktop replan action is superseded by this exact-plan flow.
  Legacy direct API clients retain their documented contract.
- No paid model request, production inventory update or GitHub publication was
  performed. Visual quality checks and the remaining operating limits are
  documented in FACTORY_SCENARIOS.md.

### Milestone 8 · Live integration and presentation review

- Exercised original phone photographs through ZIP intake, real SAM, visual
  acceptance, stock identity, real Baseten parsing, DXF upload, verified output
  and browser download in isolated storage. A second job used both sheets.
- Kept saved-photo inspection after acceptance and improved outline/hole contrast,
  readable model provenance and key-free example status.
- Reworked the README around an actual example screenshot and reproducible entry
  paths; retained engineering detail and source-backed winner/hosting research.
- **184 backend tests, 42 frontend tests, TypeScript and production build pass.**
  See the final integration report for exact evidence and limits.
- Published after user approval with the matching backend contracts and separate
  milestone history. The first hosted GitHub Checks run passed both suites and
  the production build. No private photograph or production inventory is included.
