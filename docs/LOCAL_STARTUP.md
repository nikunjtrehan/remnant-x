# Remnant X local startup guide

This guide starts the local Python backend and desktop web frontend, explains first-time setup, and walks through a photo ZIP to a reviewed cutting plan. Use two PowerShell terminals and keep both servers running. Existing projects should reuse their virtual environment and environment file.

## Requirements

- Windows with Python 3.11.
- Node.js 22.12 or newer with npm.
- This repository, normally at D:\remnant-X.
- A Meta API key for live SAM segmentation. Configure Baseten for the normal Muse Spark Open order parser; Fireworks and Meta chat access provide the configured alternatives.
- A measured four-marker station for live photo work. The recorded Example works without API keys or a backend.

The current station defaults are top 657 mm, bottom 658 mm, left 509 mm, right 514 mm, and black marker square 48 mm. These are this physical station's measurements, not universal defaults for every workshop. Use the full black marker square and exclude the white border.

## First time setup

Open PowerShell in the repository. Skip installation commands when the existing environment is already installed and working.

    Set-Location 'D:\remnant-X'
    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
    }

Edit the local .env file and set real provider keys. Do not paste keys into the frontend, source files, screenshots, Word documents or GitHub. Copying .env.example only when .env is absent protects existing credentials. Virtual-environment activation is unnecessary because the commands explicitly invoke its Python executable.

Install frontend dependencies once, or again when package-lock.json changes.

    Set-Location 'D:\remnant-X\Front End'
    npm ci

## Start the backend in terminal one

For the normal workspace, open a new PowerShell terminal:

    Set-Location 'D:\remnant-X'
    .\scripts\start.ps1

The launcher starts Uvicorn on 127.0.0.1:8000. Open http://127.0.0.1:8000/docs for API documentation. The backend reads .env and any environment variables already set in that terminal. The standard database is warehouse.db and the standard artifact folder is artifacts unless your configuration selects other paths.

The API URL is local to this computer. A localhost link in GitHub cannot start a server or open your computer's API for another person.

### Start without the PowerShell launcher

If local policy prevents running a PowerShell script, invoke the installed Python server directly. Changing execution policy is not required.

    Set-Location 'D:\remnant-X'
    .\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000

### Keep one warehouse consistently

The database and artifact folder form one workspace. Reuse the same two paths when restarting. A database stores reviewed stock and plans; the artifact folder stores the files those records reference.

To select your own stable workspace explicitly:

    Set-Location 'D:\remnant-X'
    $env:REMNANTX_DB_PATH = 'D:\remnant-X\.task-tmp\my-workspace\warehouse.sqlite'
    $env:REMNANTX_ARTIFACT_DIR = 'D:\remnant-X\.task-tmp\my-workspace\artifacts'
    .\scripts\start.ps1

Selecting a new path starts a new empty warehouse. It does not bring stock across from another database. Close the old backend before reusing its port. Keep the former database and artifact folder if you want to return to them. Do not delete a warehouse to clear a browser warning.

### Separate demonstration storage

    Set-Location 'D:\remnant-X'
    .\scripts\start.ps1 -Demo

This deliberately selects demo_warehouse.db and artifacts\demo. Startup does not seed stock. Synthetic or local-threshold stock requires an explicit planning opt-in. For an actual cardboard test, use live SAM and reviewed stock rather than synthetic seeding.

## Start the frontend in terminal two

    Set-Location 'D:\remnant-X\Front End'
    npm run dev -- --config vite.config.ts --port 5173 --strictPort

Open http://127.0.0.1:5173. The checked-in Vite configuration proxies /api to the backend at port 8000. If port 5173 is occupied, identify the existing server before opening another copy. The strict port flag prevents silently moving to a different browser origin with different saved history.

Select Live workspace for your own photographs. Example and Guided walkthrough display a labeled recorded synthetic run and do not start live inference.

## Run a fresh cardboard test

1. Open Scan a remnant and choose Batch photos / ZIP.
2. Upload a ZIP containing one photograph per physical piece. Each photograph must show all four marker IDs and their white borders.
3. Set material to cardboard and thickness to 3 mm. Apply the settings to unprocessed photos if required. The batch importer allows up to 50 JPEG/PNG images, 20 MB per image and 100 MB total.
4. Click Check markers in photos. This checks markers and calibration without calling SAM.
5. Click Find outlines & holes in the ready photos. This invokes SAM and creates pending geometry reviews.
6. Select each photograph, inspect its outer boundary and holes, confirm the geometry review, and click Accept geometry & add stock. Repeat for both pieces.
7. Check Inventory. Two uploaded photographs are not yet two available stock records until both reviews are accepted.
8. Open Plan a job. Choose the saved batch or Use all compatible inventory.

The same image bytes cannot be used repeatedly to create new stock. Recover an existing review rather than changing the filename or inventory ID to bypass duplicate protection. To repeat the entire live perception experiment, use a separate empty workspace and a separate browser origin; preserve the former workspace.

## Test a circle order

Enter this complete prompt:

    Cut 10 circles, each with a radius of 20 mm, from 3 mm cardboard.
    Kerf 1 mm.

Click Review order. The review must show quantity 10 and diameter 40 mm. A radius of 20 mm is not a diameter of 20 mm. Review the interpretation and process settings before clicking Nest & verify.

## Test an uploaded DXF

1. Add the vendor DXF under Plan a job.
2. Check its preview, hole count and converted millimetre dimensions.
3. Choose DXF material and thickness. A single available stock type can be shown automatically; several types require an explicit choice.
4. Set the displayed DXF kerf.
5. Enter: I want to cut 3 copies of this.
6. Click Review order and confirm the quantity and file binding.
7. Click Nest & verify. Inspect each sheet tab and the stock allocation list.

DXF uploads are limited to 5 MB. Supported files have one outer boundary with disjoint holes, using closed straight LWPOLYLINE or closed planar SPLINE contours. Declared mm/cm/m/inch units convert to mm. Unitless files are treated as mm. Splines are flattened with a disclosed 0.05 mm chord tolerance. Native circles, arcs, polyline bulges, blocks, open contours and invalid topology remain unsupported.

The tested decorative part is approximately 168.9 by 167.7 mm at its declared scale and contains five holes. It is not automatically resized to fit a sheet. Sheet-aligned rotations allow the actual three-copy case to place one copy on Piece B and two on Piece A. This observed result does not prove optimal nesting for every job.

## Review output and update stock

A complete plan must place the requested quantity, pass placement checks and verify every generated sheet program. Inspect the geometry, toolpath, physical sheet ID, controller profile and process settings. The current profiles are ISO_6983_GRBL and LINUXCNC_LASER.

A partial plan identifies unplaced instances and cannot be treated as a completed order. Downloading a program does not record a physical cut. Only record completion after the operator has actually used that exact saved program. The API then checks the saved stock snapshot and commits all affected sheets atomically.

Software verification does not qualify physical sheet measurement, material properties, workholding, controller setup or a laser process. Output uses centerline contours and does not perform dimensional kerf compensation.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser cannot open localhost | Keep the matching server running; check the printed port. |
| Frontend says backend disconnected or returns 404 | Start the API and use the checked-in Vite configuration. Port 5173 normally proxies to port 8000. |
| Fresh page opens the recorded example | Select Live workspace, then Scan a remnant or Plan a job. |
| Photo says already analysed | Recover its saved review or inspect the existing stock record. Use an isolated workspace for a genuinely fresh experiment. |
| L-shaped piece is absent from nesting | Check whether its geometry review was accepted and whether its batch, material and thickness are selected. |
| Empty inventory after restart | Check REMNANTX_DB_PATH and REMNANTX_ARTIFACT_DIR. A different path is a different warehouse. |
| All markers are not visible | Recapture the flat station with marker IDs 0, 1, 2 and 3, including the white borders. |
| SAM finds no matching sheet | Use a specific concept such as cardboard sheet, inspect the image, or select the intended region. |
| DXF import is rejected | Check units, supported entity types, closed planar loops and hole containment. |
| Two copies fit but a third is unplaced | Review stock selection, grain locks, scale and rotation; the bounded search may miss a legal packing. |
| A plan becomes stale | Refresh stock and generate a new plan; do not replay an old program against changed inventory. |
| Address already in use | Use the existing server or stop the correct terminal with Ctrl+C. Do not terminate unrelated processes. |

## Stop and restart

Press Ctrl+C in each server terminal. Browser history survives in that browser; stock and pending reviews survive in the selected SQLite database. Keep the matching artifact folder. After backend source changes, restart Uvicorn because the launcher does not enable automatic reload. Vite normally reloads frontend changes automatically.

## Validate before publishing

From the root:

    .\.venv\Scripts\python.exe -m pytest -q --tb=short

From Front End:

    npm run check

The backend suite uses offline providers. Live SAM smoke tests and provider benchmarks are separate, opt-in operations. Never publish .env, databases, raw local photos, artifacts, node_modules, .venv or private handoff notes.

Architectural decisions: https://nikunjtrehan.github.io/remnant-x/architecture/
