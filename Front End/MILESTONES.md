# Desktop workbench milestones

The frontend lives here; FastAPI remains the only backend. Local milestone commits
are review checkpoints. Publishing to GitHub is a separate step.

| Milestone | Deliverable | Acceptance |
| --- | --- | --- |
| 1 · Workbench | React/TypeScript/Vite shell; SVG geometry workspace; explicit example/live modes | Production build; viewer coordinate and selection tests |
| 2 · Capture | Station profile, photo preflight, marker overlays, SAM indexing and inventory | Missing markers block analysis; changed inputs invalidate preflight; no preflight model/DB writes |
| 3 · Manufacturing | Prompt review, multi-DXF tray, batch nesting, verification, downloads and explicit predicted-stock update | Real API contract; partial/unsafe outputs cannot masquerade as a complete job; stale UI results invalidated |
| 4 · Demonstration | Backend-generated synthetic example; guided visual replay; accessible interactions and browser checks | Replay stays separate from live work; browser-tested photo failures and actual offline batch execution |

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
