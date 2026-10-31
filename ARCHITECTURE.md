# RemnantX Architecture

RemnantX is a local manufacturing workbench for converting calibrated photographs
of sheet remnants into reviewed inventory, placing requested parts across that
inventory, and generating software-verified CNC programs. Its central separation
is simple: models perceive images and interpret orders; local geometry determines
placements and checks the final output. The operator accepts stock geometry and
reports when a physical cut has actually happened.

This document describes the implemented system. For setup, see the
[local startup guide](docs/LOCAL_STARTUP.md). For the reasons behind the design,
benchmarks and physical experiments, visit the
[engineering decisions website](https://nikunjtrehan.github.io/remnant-x/engineering-decisions/).

## System topology

```text
Desktop browser                          Local Python service
React + TypeScript                       FastAPI + Uvicorn
  Plan a job          --- HTTP/JSON --->   api.py
  Scan a remnant      --- multipart --->    |-- photo_preflight.py
  Inventory                               |-- m1_sam_indexer.py --> Meta SAM 3.1
  Geometry review                         |-- m2_spark_orchestrator.py
  Cutting-plan viewer                     |     `-- llm_client.py --> Order providers
                                          |-- pipeline.py
IndexedDB: photos and batch drafts         |     |-- m3_nfp_nester.py
localStorage: station and job draft        |     `-- m4_muse_gcode.py
                                          |-- review_workflow.py
                                          `-- db_and_parts.py
                                                 |-- SQLite warehouse
                                                 `-- Managed DXF artifacts

Preparation outside the job loop:
Muse Code --> checked-in controller emitters --> final-program verification
```

During development, Vite normally serves the browser at `127.0.0.1:5173` and
proxies `/api` to the backend at `127.0.0.1:8000`. The public decision website is
static documentation on GitHub Pages; it does not host the backend. The frontend
production build also requires an appropriate API deployment/proxy for live work.
The recorded Example can be explored without a backend or provider keys.

Requests use ordinary HTTP responses, not WebSockets or a durable background-job
queue. A nesting request stays pending while the backend computes. The browser's
elapsed-time display is not server progress telemetry; closing the page does not
provide a coordinated cancellation protocol.

## Repository layout

```text
remnant-x/
  README.md                       Product overview and quick start
  ARCHITECTURE.md                  This system reference
  requirements.txt                Backend runtime dependencies
  requirements-dev.txt            Offline test dependencies
  .env.example                    Configuration names without credentials
  backend/
    api.py                        HTTP routes and application factory
    schemas.py                    Validated request contracts
    serialization.py              Geometry and result response conversion
    photo_preflight.py            Capture checks before model inference
    m1_sam_indexer.py              ArUco rectification and mask vectorization
    sam_client.py                 Meta segmentation transport and decoding
    llm_client.py                 Chat providers and sequential failover
    materials.py                  Material and grade identities
    order_intent.py               Missing-input and contradiction checks
    m2_spark_orchestrator.py       Order parsing, CAD construction, stock query
    db_and_parts.py               SQLite warehouse and CAD import/export
    m3_nfp_nester.py               Hole-aware placement and bounded search
    m4_muse_gcode.py               Toolpaths, compilation and final verification
    postprocessor.py              Restricted prepared-emitter contract
    postprocessors/               Prepared GRBL/LinuxCNC emitters and provenance
    pipeline.py                   Complete manufacturing request orchestration
    review_workflow.py            Durable reviews, saved plans and confirmation
    tests/                        Offline contract and integration regressions
  Front End/
    src/                          React workflows, SVG rendering and recovery
    public/example/               Recorded synthetic inputs and backend output
    vite.config.ts                Development proxy and test configuration
    package.json                  Frontend scripts and dependencies
  scripts/                        Startup and explicit preparation/smoke tools
  benchmarks/                     Provider comparison cases and reporting
  docs/
    ENGINEERING_GUIDE.md           Detailed API, CAD and controller contracts
    CODEBASE_GUIDE.md              File-by-file implementation reference
    LOCAL_STARTUP.md               Local operation and troubleshooting
    engineering-decisions/        Public decision website entry point
    architecture/                 Experiment reports, fixtures and evidence
    assets/                       README application screenshots
  .github/workflows/               Offline checks and documentation publication
```

The `m1` through `m4` names follow the perception, interpretation, placement and
compilation stages. They are Python modules in one service, not separate deployed
microservices. The existing `docs/architecture` evidence paths remain stable even
though the public website is named Engineering Decisions.

## Core data contracts

| Type or record | Role |
| --- | --- |
| `StationCalibrationConfig` | Measured station dimensions, marker size and image mapping |
| `RemnantRecord` | Physical stock ID, exact material, thickness, polygon, provenance and location |
| `ManufacturingOrderSpec` | Validated material, thickness, kerf and requested part quantities |
| `CADPartSpec` | Actual part polygon, holes, quantity and grain restriction |
| `PlacedPartInstance` | One requested copy with a pose and transformed polygon |
| `SheetNestingOutcome` | Placements and remaining area for one stock record |
| `CompiledSheetGCode` | Final program, origin, ordered loops and verification result |
| Intake review | Persisted analysis waiting for geometry acceptance |
| Verified plan | Exact result/programs bound to request and stock snapshots |

Shapely polygons carry an exterior and interior rings. Holes are empty space,
not dark pixels that become available stock. SQLite persists stock polygons as
WKT; serialization converts them into coordinate arrays for the frontend.
Image coordinates use X right/Y down; geometric coordinates use millimetres with
X right/Y up. Each compiled program records its translated work origin.

## Photo intake and geometry review

```text
Choose single photo or ZIP batch
  -> validate image type, size, count and duplicate bytes in the browser
  -> enter material, thickness, physical identity and station configuration
  -> POST /api/v1/photo-preflight
  -> detect all required marker IDs and check calibration consistency
  -> POST /api/v1/index-remnant with a review ID
  -> rectify station image -> request SAM mask -> vectorize exterior and holes
  -> save pending optical review in SQLite
  -> worker compares the overlay with the photograph
  -> POST /api/v1/intake-reviews/{review_id}/accept
  -> accepted geometry becomes available warehouse stock
```

The browser stores top/bottom and left/right station spans; its API adapter sends
their respective averages as station width/height. The measured black marker
square excludes its white margin. Defaults describe the measured development
station and must be changed for a different physical installation.

OpenCV detects markers, warps the image and extracts contours. In the live path,
Meta SAM 3.1 supplies the segmentation mask through the Responses endpoint and
the official mask parser. Missing credentials, incomplete output or no matching
object are failures; they do not silently select local thresholding. Optional
CLAHE changes lighting input. Explicit local-threshold demonstrations retain
separate provenance and require planning opt-in.

A concept prompt or a box in the rectified image identifies the intended sheet.
Segmentation does not identify alloy or thickness; those are explicit stock
inputs. Calibration consistency does not prove physical contour accuracy.

The UI uses `save_to_warehouse=false` and a pending review. A passed analysis is
not accepted inventory. Acceptance checks stock identity and blocked/truncated
captures inside a database transaction. Rejecting an already accepted review
does not remove its stock. The direct API also retains explicit legacy save
options for trusted local callers.

## Batch intake and stock selection

`PhotoBatch.tsx` maintains named batches and per-photo states. The browser accepts
up to 50 JPEG/PNG photos, 20 MB per image and 100 MB expanded image data per batch.
`photo-import.ts` checks actual limits and duplicate image bytes, including ZIP
contents. Each image should represent a different physical remnant.

Shared material/thickness settings apply to unprocessed items. Marker checks are
separate from paid SAM analysis. Batch analysis processes photographs sequentially;
each photo has its own success, failure, retry and review. A failed image does not
discard another accepted stock record. Each result still needs visual acceptance.

Named batch history is stored in this browser, not as a server-owned batch table.
Accepted sheet IDs from a selected batch become `selected_sheet_ids` on a job.
The backend intersects those IDs with material/thickness-compatible stock. It
does not borrow unselected sheets if the chosen batch cannot fill an order.

Exact image-byte protection prevents reusing the same capture as new stock.
It does not recognize every different photograph of the same physical sheet.
Physical labels and worker identity checks remain part of the workflow.

## Order interpretation and DXF import

There are two ways to describe parts: a natural-language prompt reviewed in the
parts editor, or explicit structured parts, including uploaded DXF definitions.
`order_intent.py` checks missing and contradictory requirements before acceptance.
Schema-valid model output must also agree with the explicit request. Circle
radius is converted to diameter; ambiguous dimensions require clarification.

The default order provider is Baseten Muse Spark Open. `llm_client.py` provides
sequential transport failover across configured providers. A rejected complete
extraction can receive one grounded Fireworks repair, unless Fireworks already
produced that extraction. The repair passes the same intent and schema checks.
A bounded deterministic parser can handle supported requests when the configured
cloud transports fail. Provider traces distinguish model output, repair and local fallback.

For vendor CAD:

```text
DXF file -> POST /api/v1/upload-dxf
  -> validate units, entities, planarity, closure and topology
  -> flatten supported splines and convert declared units to millimetres
  -> store canonical polylines under a generated managed upload path
  -> show dimensions and holes -> bind the file to requested quantities
  -> construct CADPartSpec from the managed geometry
```

The importer accepts one outer boundary with disjoint holes using closed straight
LWPOLYLINE or closed planar SPLINE loops. Declared mm/cm/m/inch units are converted;
unitless means mm. Splines use a disclosed 0.05 mm chord tolerance. Native
circles/arcs, bulges, blocks, open/3D geometry and invalid hole topology are
unsupported. Uploads are bounded to 5 MB. This contract is intentionally narrower
than arbitrary industrial CAD support.

With one uploaded file, “I want to cut 10 copies of this” uses the visible UI
material/thickness and editable kerf context. Conflicting prompt/context is
rejected. Several uploaded files use explicit file-bound parts and quantities.
Uploads create part definitions, not warehouse sheet inventory.

## Planning and nesting flow

```text
Reviewed order + process/search settings + optional selected stock IDs
  -> validate managed DXF bindings and resolve controller profile
  -> query exact material and thickness-compatible inventory
  -> restrict stock selection and exclude demo stock unless explicitly allowed
  -> order candidates by smallest usable area
  -> expand requested quantities into individual part instances
  -> place parts with hole-aware NFP/contact proposals
  -> run bounded alternative part-order searches where applicable
  -> independently sanitize placements
  -> compile and verify every used sheet
  -> return counts, layouts, traces, metrics and final programs
```

The initial part order prefers larger envelopes; failed large parts can spill
to later sheets while smaller parts backfill. Stock holes remain excluded.
Usable centers inside ring-shaped parts can be reused when geometry permits.

Unlocked parts test station quarter-turns and quarter-turns aligned with the
stock's minimum rotated rectangle. This avoids making a photographed sheet's
rotation an artificial packing restriction. Grain-locked parts retain the
station 0/180 policy; a material grain frame is not inferred from the photo.

NFP work has fixed decomposition/operation budgets. If that budget is exceeded,
a disclosed bounded grid proposes placements against the unchanged polygons,
with at most 10,201 positions per orientation. Coverage, hole clearance, part
separation and the independent sanitizer still apply.

The search is heuristic. “Unplaced” means this search did not find a legal pose,
not that none exists. The response explicitly reports `globally_optimal=false`.
The [rotated-stock experiment](docs/architecture/ROTATED_STOCK_NESTING.md) records
the actual three-copy job: one part on Piece B and two on Piece A, with both
final programs verified.

## Parallel work and the preparation boundary

Local `ThreadPoolExecutor` chains explore seeded simulated-annealing changes to
part ordering. Search settings bound iterations and workers; defaults are two
iterations per chain and two workers. Identical-geometry orders or disabled
annealing use one chain to avoid redundant work. Search traces report actual
workers, evaluated layouts, seed and fallback use. Multiple Python threads do
not guarantee a proportional CPU speedup.

This local search parallelism is separate from cloud inference. Mandatory
Baseten/Fireworks agreement is not the production routing policy; its measured
latency and interpretation tradeoffs are recorded on the decision website.
SAM capture and later order interpretation also happen at different workflow stages.

Muse Code operates during explicit controller-emitter preparation. The checked-in
GRBL/LinuxCNC emitters and provenance are reused per job. `postprocessor.py`
validates a narrow Python AST/formatting contract; uploaded executable Python is
not a supported postprocessor mechanism. There is no coding-agent call on every
compile. Interactive image/order calls remain in the workflow; repeated placement
and verification stay in ordinary code.

## Compilation and verification

`m4_muse_gcode.py` orders internal contours before enclosing cuts, translates the
sheet to its reported work origin, builds numeric loops and optional bounded arc
lead-ins, then formats the requested prepared controller profile.

Supported profiles are `ISO_6983_GRBL` and `LINUXCNC_LASER`. Every final emitted
program is reparsed and checked against the planned loops and shifted stock:

- Supported opcodes, parameters, setup and end state.
- Explicit feed, power and dwell values, with no active-laser rapid motion.
- Closed contours, correct cut ordering and agreement with planned paths.
- No cutting across existing stock holes or outside the supplied sheet.
- Clearance envelopes for supported arc lead-ins.

One failed program rejects the pipeline result before any inventory commitment.
A partial placement can be inspected, but cannot be committed as a complete job;
the frontend also gates complete-order downloads and confirmation.

`verified_safe` is a software result for the supplied geometry, command subset
and process values. It does not qualify the physical sheet, controller wiring,
hold-downs or laser process. Output uses centerline contours: kerf reserves
placement clearance and predicted stock loss, not dimensional cutter compensation.

## Saved plans and cut confirmation

```text
New job -> reviewed order -> nesting request -> complete verified preview
                                           |-> partial result: revise job
                                           `-> failure: inspect error

Complete preview + plan ID -> stored exact plan -> worker downloads/reviews
  -> physical cutting outside this application
  -> explicit operator confirmation
  -> validate stored stock snapshots -> one inventory transaction + receipt
```

`review_workflow.py` persists complete verified plans with their request hash,
programs, consumed geometries, expected stock WKT and material/thickness/source.
Recovering a plan does not automatically recompute it. Changed inputs require a
new plan identity; changed stock is reported as stale.

Confirmation uses the stored cuts rather than running nesting again. A SQLite
`BEGIN IMMEDIATE` transaction checks the snapshots, applies all sheet updates and
writes the completion receipt together. A repeated confirmation returns the
receipt instead of consuming stock twice. Any failure rolls back the transaction.
Disconnected remaining islands become distinct inventory records; outdated
stock DXF references are cleared. Pieces must be reindexed after physical movement.

The direct API's explicit `commit_cuts_to_db=true` path remains for trusted
callers. The desktop uses preview, saved plan and operator confirmation instead.
Neither path sends commands to a machine or senses physical completion.

## HTTP interface

| Route | Responsibility |
| --- | --- |
| `GET /api/v1/health` | Service status and configured-provider flags |
| `POST /api/v1/photo-preflight` | Marker and station consistency checks |
| `POST /api/v1/index-remnant` | Analysis and pending review creation |
| `GET /api/v1/intake-reviews` and `/{id}` | Pending review discovery/recovery |
| `POST /api/v1/intake-reviews/{id}/accept` or `/reject` | Geometry review decision |
| `GET` / `POST /api/v1/remnants` | Stock query or explicit stock insertion |
| `POST /api/v1/remnants/{id}/location` | Physical storage label update |
| `POST /api/v1/upload-dxf` | Validated managed part import |
| `POST /api/v1/parse-order` | Interpreted order for worker review |
| `POST /api/v1/execute-pipeline` | Placement, compilation, verification and optional plan storage |
| `GET /api/v1/verified-plans/{id}` | Recover exact saved output |
| `POST /api/v1/verified-plans/{id}/confirm` | Report cut completion and update stock |
| `GET /api/v1/artifacts/{filename}` | Download managed indexed DXFs |

Pydantic request models reject unknown fields, non-finite numbers and out-of-range
settings. Managed DXF paths are checked to stay under the upload root. The frontend
API adapter translates failures into readable notices with support details.
The running service exposes its full OpenAPI contract at `/docs`.

## Frontend responsibilities

| Module | Owns |
| --- | --- |
| `App.tsx` | Plan/Scan/Inventory navigation, live/example mode and inventory refresh |
| `Scanner.tsx`, `Capture.tsx` | Shared station setup and single-photo capture workflow |
| `PhotoBatch.tsx`, `photo-import.ts` | Named ZIP/photo queues, limits, per-photo results and history |
| `GeometryReview.tsx`, `PhotoRegion.tsx` | Outline acceptance and region prompts |
| `Plan.tsx`, `OrderEditor.tsx` | Prompts, DXF quantities, stock selection, review and planning |
| `CuttingPlan.tsx`, `SheetViewer.tsx` | Counts, stock allocation, SVG geometry, planned paths and downloads |
| `Inventory.tsx`, `stock-label.ts` | Available physical stock and labels |
| `recovery.ts`, `station.ts` | Browser persistence and station validation |
| `api.ts`, `types.ts`, `verification.ts` | HTTP contracts and complete-plan UI gates |

SVG displays server polygons and program paths; the browser does not perform
manufacturing nesting. Path playback is a visualization, not a machine-physics
simulation. Upload quantity changes invalidate/synchronize the reviewed order.
The recorded Example is labelled synthetic and separate from live inventory.

## Storage and recovery

| Store | Contents | Authority |
| --- | --- | --- |
| SQLite `remnants` | Geometry, material, thickness, identity, provenance and location | Available stock |
| SQLite `intake_reviews` | Analysis payloads and pending/accepted/rejected state | Optical review decisions |
| SQLite `verified_plans` | Exact result, cuts, stock snapshots and receipt | Plan recovery and completion |
| Artifact directory | Managed uploads and indexed DXFs | Files referenced by records |
| Browser IndexedDB | Original photo files and named batch drafts | Local intake recovery |
| Browser localStorage | Station, view and job convenience state | Browser draft only |

`REMNANTX_DB_PATH` and `REMNANTX_ARTIFACT_DIR` select a paired workspace. Switching
the database does not migrate stock. Browser storage is scoped to origin: another
browser or port can show different history while using the same server warehouse.
Recovering a browser draft never automatically repeats SAM analysis.

Importing the API module does not seed a warehouse. Demo storage and seeding are
explicit; demonstration stock retains provenance. Original photos are retained
in the browser, with analysis/frame data in review payloads. Keep both the database
and matching artifacts when preserving a workspace.

## Configuration and deployment boundaries

Python reads provider configuration from local environment settings. `.env` and
real credentials stay outside Git and the frontend bundle. `.env.example`
documents the names; health output exposes configuration flags, not key values.
Use Python 3.11 and the pinned backend dependencies; the frontend requires a
Node version supported by its Vite build, documented in the startup guide.

The launcher binds to loopback. This prototype has no user authentication,
multi-tenant authorization or production network perimeter; CORS is permissive.
Publishing GitHub Pages does not make the manufacturing API public. A hosted
multi-user service would require those controls and a durable job/cancellation
design before exposure.

## Evidence, tests and extension points

The offline suite exercises geometry, stock filtering, unknown commands, final
program tampering, real SQL rollback, stale/replayed plans, grade separation,
DXF import, SAM response decoding and end-to-end workflows. Frontend tests cover
intake/history recovery, review gates, DXF binding, stock choice and result display.
GitHub Actions runs the backend suite and frontend tests/TypeScript/build checks.
Live model smoke tests and provider benchmarks are explicit separate operations.

Two cardboard specimens and eight captures form the current physical-validation
evidence. Five captures produced usable topology and three were blocked. Reported
exterior error reached 7.32 mm; some ruler references were corrected after seeing
outputs. These experiments do not establish uniform millimetre accuracy or
qualification for reflective metal and industrial cutting.

Extend CAD at the import boundary and canonicalize the reviewed geometry. Extend
controllers through explicit emitter/profile contracts and final verification.
Add providers where interpretation or perception has a measured purpose. Preserve
geometry review, exact grade matching, selected-stock restrictions, stale-state
checks and atomic completion when adding features.

Measured utilization and timings describe a run. Money and CO2 savings remain
unset until an equivalent-production baseline and explicit assumptions exist.
For protocol details, see the [engineering reference](docs/ENGINEERING_GUIDE.md);
for module-level explanation, see the [codebase guide](docs/CODEBASE_GUIDE.md).
