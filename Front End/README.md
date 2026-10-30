# Remnant X workbench

Desktop-first React + TypeScript application. FastAPI owns perception, order
interpretation, placement and final verification; the browser renders results.

## Local development

From the project root, start the API using `scripts/start.ps1 -Demo` in one terminal.
Demo stock is still seeded explicitly in the UI, never at startup.

In a second PowerShell terminal:

```powershell
Set-Location 'Front End'
npm ci
npm run dev
```

Open the printed address, normally `http://127.0.0.1:5173`. Vite proxies `/api`
to `http://127.0.0.1:8000`. No provider credentials belong in this folder or the
browser. The backend reads its existing environment configuration.

```powershell
npm run check
```

This runs interaction/unit checks and a production TypeScript/Vite build.
`npm run preview` previews that build. Development proxying is not included in
the production build: deployment needs a same-origin `/api` reverse proxy to
FastAPI. Hosting and GitHub publication are separate future steps.

## Workflows

- **Example:** starts with a captured result for 28 parts on one synthetic
  L-cutout remnant. Guided chapters explain the photo, geometry, nesting and
  verified output. Actual recorded G-code and result JSON are downloadable.
- **Live scanner:** save station spans and black marker size; choose a photograph;
  inspect actual detected markers and rectified preview. Missing markers or bad
  calibration block analysis. An optional box can target the sheet in rectified
  pixels. “Analyze for geometry review” calls SAM and stores a pending review.
  Compare the outline and holes over the calibrated photograph, then accept it
  before it becomes available stock. Rejected geometry can be recaptured or refined.
- **Batch photos / ZIP:** import loose JPEG/PNG photos or a ZIP, up to 50 photos,
  20 MB per image and 100 MB total. Configure shared defaults, inspect per-photo
  overrides, check pending photos, then analyze the ready ones. Bad photos remain
  visible; successful photos are not repeated. Each photograph must show one
  distinct remnant and all four station markers.
- **Live planning:** describe a job and review the parsed order, or build a parts
  list directly. Upload vendor DXFs in batches with independent quantities and
  per-file errors. Review material/grade, dimensions, kerf and controller inputs.
- **Result:** inspect sheets, parts, kerf zone, planned cut sequence and final
  verification. A partial batch remains visibly partial and cannot update stock.
  Changing order inputs invalidates the earlier result.
- **Stock identity:** enter the ID written on the physical sheet and its rack/slot.
  Inventory can update locations and download printable SVG labels. The cutting
  plan identifies the physical sheet to retrieve. Different photographs do not
  prove different physical stock.
- **Stock update:** “Record completed cut” requires the operator to confirm use
  of the exact saved program. Current stock must match the saved snapshot. The
  backend atomically updates all sheets from that stored plan without renesting.
  A download alone never confirms cutting. Remaining geometry is still predicted;
  there is no machine connection or automatic physical-cut verification.

Single and batch capture share one station profile, persisted in browser local
storage. A batch processes sequentially through the existing API. Each accepted
sheet is saved independently; this intake is not one atomic warehouse transaction.
The manufacturing batch commit retains its existing all-sheets verification and
atomic transaction. “Stop after current photo” does not cancel a running request.
Exact duplicate image bytes are detected in the queue and across reviewed scans
on the backend. Live job drafts use local storage; original single/batch photo
files and metadata use IndexedDB. Views and capture mode restore after reload.
Recovery never restarts model inference automatically. Completed analyses and
cut plans are stored in SQLite with stable IDs; acceptance and cut-confirmation
retries replay their durable result. Pending geometry can also be recovered from
Inventory if the local queue is unavailable. Storage failures are shown explicitly.
Recovery requires the same browser origin and backend database. Clearing browser
data removes unsent photos; an interrupted server computation may need an explicit
retry. There is no background job service or cancellation of an active model call.

## Reproduce the recorded example

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.record_frontend_example
```

This uses a synthetic image, explicit local-threshold segmentation, an in-memory
database, actual NFP placement and final G-code verification. It needs no API keys
and never reads the physical test photos or production warehouse. The generated
record includes source, image hash, station dimensions, order and measured timings.
It is stored as compact JSON to avoid thousands of generated coordinate lines in
source review. The walkthrough reuses the same millimetre viewer as live output.

`App` owns navigation/mode and warehouse retrieval. `Capture` owns the photo gate.
`Plan` owns order input and requests; `CuttingPlan` owns sheet inspection/playback.
`SheetViewer` renders the returned geometry; `api` is the HTTP boundary. CSS is
plain CSS; the app has no additional backend, agent framework or 3D dependency.

See [VALIDATION.md](VALIDATION.md) for the checks and remaining integration limits.
The [workflow guide](WORKFLOW_GUIDE.md) explains batch behavior and design decisions.
The [factory scenario matrix](FACTORY_SCENARIOS.md) distinguishes automatic
guards, operator checks and remaining deployment limits.

See [MILESTONES.md](MILESTONES.md) for scope and validation checkpoints.
