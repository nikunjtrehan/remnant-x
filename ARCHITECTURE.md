# Remnant X Architecture

Remnant X is a desktop-first manufacturing workbench for turning photographed sheet remnants into reviewed digital stock, then planning new parts against that stock. A worker captures each remnant on a calibrated ArUco station, reviews its reconstructed boundary and holes, describes an order or imports vendor DXFs, and inspects a verified cutting plan before any inventory is updated.

The architecture is deliberately split at the trust boundary: AI models provide image segmentation and order interpretation; conventional geometry code builds, places and checks the parts; a worker accepts stock geometry and later confirms that a physical cut was completed. Remnant X is a supervised local prototype, not a machine controller.

For setup, see the [local startup guide](docs/LOCAL_STARTUP.md). For design trade-offs and experiments, see the [Engineering Decisions site](https://nikunjtrehan.github.io/remnant-x/engineering-decisions/).

## System Topology

    Operator / workshop worker
              |
       Desktop browser
       React 19 + TypeScript + Vite
    +------------------------------------------+
    | Plan a job | Scan a remnant | Inventory  |
    | Photo/ZIP intake | Geometry review       |
    | Order editor | Cutting-plan viewer       |
    +---------------------+--------------------+
                          |
                HTTP / JSON / multipart
                     /api/v1/*
                          |
                Local Python service
                   FastAPI + Uvicorn
    +---------------------+--------------------+
    | api.py - route and request boundary      |
    |                                          |
    | Photo path              Job path          |
    | photo_preflight.py      m2_spark_...      |
    | m1_sam_indexer.py       order_intent.py   |
    |   |                     pipeline.py       |
    |   +--> sam_client.py      |               |
    |                          +--> m3_nfp_...  |
    |                          +--> m4_muse_... |
    |                                          |
    | review_workflow.py   db_and_parts.py      |
    +-----------+------------------+-----------+
                |                  |
           SQLite store       Managed artifacts
         stock / reviews      DXF uploads / exports
         saved plans /        and indexed geometry
         completion receipts
                |
       External model endpoints
      +----------+----------------------+
      | Meta SAM 3.1 - photo masks      |
      | Muse Spark Open - order parsing|
      | Baseten / configured failover  |
      +--------------------------------+

The diagram shows one backend process, not a collection of deployed microservices. The m1–m4 modules are stages inside the same Python application. Provider calls are made by backend clients; API credentials are not placed in the browser.

During local development, Vite serves the frontend at 127.0.0.1:5173 and proxies /api to FastAPI at 127.0.0.1:8000. Requests are ordinary synchronous HTTP calls. There is no WebSocket event stream, durable background-job queue or machine-control connection. A long nesting request remains open while the backend computes.

The public GitHub Pages site hosts engineering documentation only. It does not host the live workbench or the local warehouse API. A production frontend build requires a separately configured deployment and an API reverse proxy.

## Repository Layout

    remnant-x/
      README.md                       Product overview and quick start
      ARCHITECTURE.md                  This system reference
      .env.example                    Backend configuration template
      requirements.txt                Backend runtime dependencies
      requirements-dev.txt            Development and offline test dependencies

      Front End/
        src/
          App.tsx                     Navigation, workspace mode and inventory refresh
          Scanner.tsx, Capture.tsx    Station setup and single-photo intake
          PhotoBatch.tsx              Named photo and ZIP batch workflow
          GeometryReview.tsx          Human review of detected stock geometry
          Plan.tsx, OrderEditor.tsx   Order input, DXFs and stock selection
          CuttingPlan.tsx              Results and cutting-plan interaction
          SheetViewer.tsx              Sheet, part and toolpath rendering
          api.ts                      HTTP client and response/error mapping
          photo-import.ts             Photo/ZIP validation and import
          recovery.ts                 Browser-side recovery helpers
        public/example/               Recorded, synthetic walkthrough
        package.json                  React, Vite, TypeScript and test scripts
        vite.config.ts                Development API proxy

      backend/
        api.py                        FastAPI application and HTTP routes
        schemas.py                    Strict request models
        serialization.py              Geometry and response conversion
        photo_preflight.py            Image and marker preflight
        sam_client.py                 Meta SAM request and mask decoding
        m1_sam_indexer.py              ArUco calibration and mask vectorization
        llm_client.py                 Baseten / Fireworks / Meta chat transport
        order_intent.py               Missing-input and contradiction checks
        m2_spark_orchestrator.py       Order interpretation and stock matching
        db_and_parts.py               SQLite warehouse and CAD import/export
        materials.py                  Material and grade normalization
        m3_nfp_nester.py               Hole-aware placement and bounded search
        m4_muse_gcode.py               Toolpath creation and program verification
        postprocessor.py              Restricted prepared-emitter interface
        postprocessors/               Checked-in GRBL and LinuxCNC emitters
        pipeline.py                   End-to-end manufacturing orchestration
        review_workflow.py             Durable review, plan and confirmation logic
        tests/                        Offline unit, API and integration regressions

      scripts/
        start.ps1                     Local backend launcher
        record_frontend_example.py    Rebuild the synthetic recorded example
        prepare_postprocessor.py      Explicit Muse Code emitter-preparation tool
        smoke_sam.py                  Opt-in live SAM smoke test

      benchmarks/                     Order-interpretation comparison tooling
      docs/
        LOCAL_STARTUP.md              Setup and local operating procedure
        ENGINEERING_GUIDE.md          API, CAD and controller contracts
        CODEBASE_GUIDE.md             File-by-file implementation guide
        FINAL_READINESS.md            Integration evidence and remaining limits
        engineering-decisions/        Public Engineering Decisions landing page
        architecture/                 Experiment reports, fixtures and measurements
      .github/workflows/               Offline checks and GitHub Pages publication

The frontend and backend are separate projects in one repository. The frontend is a browser application; it is not an Electron application. The backend owns the manufacturing calculations and durable warehouse records.

## Photo Intake: Photograph to Reviewed Inventory

    Photo or ZIP batch
      -> browser validates file type, byte size and duplicate bytes
      -> worker supplies station dimensions, marker size and stock identity
      -> POST /api/v1/photo-preflight
      -> detect required ArUco markers and check calibration consistency
      -> POST /api/v1/index-remnant
      -> rectify image into the station plane
      -> Meta SAM 3.1 returns a segmentation mask
      -> vectorize the exterior boundary and interior holes
      -> persist a pending geometry review
      -> worker compares overlay with the source photograph
      -> accept or reject the review
      -> accepted geometry becomes warehouse inventory

### Calibration and perception

The station is a measured physical reference, not an arbitrary photograph. Four identified ArUco markers and their corners establish the planar homography. The measured black marker square supplies the physical scale. The frontend stores the top/bottom and left/right station spans and sends their averages as table width and height.

photo_preflight.py checks marker presence, duplicate IDs and calibration consistency before the live segmentation request. A failed preflight can be corrected without paying for a SAM inference. Passing preflight does not prove that the final contour is physically exact.

m1_sam_indexer.py rectifies the image with OpenCV, requests a mask through sam_client.py, and vectorizes the mask into a Shapely polygon. The polygon retains one exterior ring and its interior rings. The live segmentation path uses Meta SAM 3.1; a missing credential, malformed response or missing target object is an error, not a silent switch to a local threshold mask. The explicit local-threshold demonstration has separate provenance.

SAM identifies image regions; it does not determine alloy, grade or thickness. Those values, together with the physical sheet ID and location, are supplied by the worker.

### Geometry review gate

Live intake creates a pending review rather than immediately making the remnant usable. review_workflow.py persists the analysis and its request identity. The browser displays the outline and holes over the calibrated photograph. The worker can accept or reject it.

Acceptance validates the stock identity and blocked/truncated geometry conditions before inserting the remnant. A rejected or pending review is not compatible stock. Batch photographs are analysed sequentially and accepted independently: failure on one photo does not roll back another photo that was already accepted. This is intentionally different from the all-sheets transaction used when recording a completed manufacturing job.

The browser batch importer supports JPEG/PNG photos and ZIP contents, with limits enforced before analysis. Each photo should represent a distinct physical remnant and show all required station markers. Exact duplicate image bytes are rejected; different photographs of the same physical sheet still require a physical ID and worker check.

## Order Intake: Prompt or Vendor DXF

A job begins with either a natural-language request or explicit structured part definitions. The worker reviews the interpreted order and process inputs before asking the geometry engine to place anything.

### Natural-language interpretation

    Prompt + visible material / thickness / kerf context
      -> POST /api/v1/parse-order
      -> SparkWarehouseOrchestrator
      -> LiveModelClient (configured provider order)
      -> structured order extraction
      -> order_intent.py checks omissions and contradictions
      -> Pydantic/schema and CAD binding validation
      -> reviewed ManufacturingOrderSpec

The default order provider is Baseten Muse Spark Open. llm_client.py supports configured Baseten, Fireworks and Meta endpoints and attempts providers sequentially according to the configured preference and available credentials. The orchestrator can request one grounded Fireworks repair for a rejected complete extraction, subject to the same intent and schema checks. A bounded deterministic parser handles a limited supported prompt grammar when cloud transports are unavailable; it is not a general-purpose natural-language model.

The model extracts the requested job. It does not choose physical stock by inventing material data, decide legal placements, write per-job controller code or certify the final program. Missing and contradictory dimensions, quantities, material or file references must be resolved before execution.

### Vendor CAD import

    DXF upload
      -> POST /api/v1/upload-dxf
      -> size, entity, unit and topology validation
      -> supported curves converted to canonical millimetre polylines
      -> geometry preview and hole count returned to the browser
      -> file path bound to the requested part and quantity
      -> CADPartSpec

The managed importer accepts one outer boundary with disjoint holes, represented by closed straight LWPOLYLINE or closed planar SPLINE loops. Declared mm/cm/m/inch units are converted to millimetres; unitless files are treated as mm. Splines are adaptively flattened with a 0.05 mm chord tolerance and must close geometrically. Uploads are limited to 5 MB. Native circles/arcs, bulges, blocks, open or 3D geometry, and invalid hole topology are outside the supported import contract.

An uploaded DXF defines a requested part; it is not a sheet of warehouse stock. Managed upload paths are checked before downstream use and are constrained to the configured upload directory.

## Planning Mode Flow: Order to Verified Cutting Plan

    Reviewed order + process settings + optional selected stock IDs
      -> validate order and managed DXF references
      -> resolve controller profile and material requirements
      -> query exact material / thickness-compatible remnants
      -> apply selected-stock restriction and demo-stock opt-in
      -> expand requested quantities into part instances
      -> propose hole-aware placements using NFP/contact geometry
      -> explore bounded alternative part orders when enabled
      -> independently sanitize placements against original polygons
      -> compile each used sheet for the selected controller profile
      -> reparse and verify every final program
      -> return sheet layouts, metrics, traces and G-code
      -> save an exact plan only when the requested quantity is fully placed

### Stock selection and CAD construction

m2_spark_orchestrator.py validates the order, binds supported parametric parts or managed DXF geometry, and constructs CAD part specifications. The warehouse query matches normalized material identity and thickness. If a batch or explicit sheet selection is supplied, it restricts the candidate set; the pipeline does not silently borrow unselected stock to fill an order. Demo stock is excluded unless explicitly enabled.

A remnant is represented by its actual polygon, including holes, not by its bounding rectangle. Stock records are considered by usable area. The order is expanded into individual requested instances before placement.

### Hole-aware nesting and bounded search

m3_nfp_nester.py uses no-fit-polygon/contact proposals to place parts while preserving the geometry of the stock and its voids. Larger part envelopes are attempted first; parts that do not fit can spill to later sheets while smaller parts backfill. Where the geometry permits it, material inside a ring-shaped part's centre can be reused.

Unlocked parts consider quarter-turn orientations in both the station frame and the stock's minimum-rotated-rectangle frame. This matters because calibration establishes scale and a planar reference; it does not require a physical remnant's edges to align with the station axes. Grain-locked parts retain their more restrictive station-frame rotation policy.

The search is bounded. Seeded local simulated-annealing chains can explore alternative part orders using a limited number of workers and iterations. If NFP decomposition exceeds its operation budget, a bounded grid can propose candidate positions against the unchanged polygons. All accepted proposals still pass the independent placement sanitizer for containment, sheet-hole clearance and part separation.

The result reports when copies remain unplaced and exposes search traces. The search is heuristic: globally_optimal=false is explicit. “Unplaced” means the bounded search did not find a legal position; it is not proof that no possible arrangement exists. See the [rotated-stock experiment](docs/architecture/ROTATED_STOCK_NESTING.md) for the recorded three-copy DXF case across Piece B and Piece A.

## Compilation and Final-Program Verification

m4_muse_gcode.py converts accepted placements into ordered cut loops. Interior contours are ordered before enclosing exterior cuts. The sheet is translated to a reported work origin, and optional bounded arc lead-ins are generated where supported.

The supported profiles are:

- ISO_6983_GRBL
- LINUXCNC_LASER

Each final program is reparsed and checked against the planned loops and shifted sheet geometry. Checks cover the supported command/parameter subset, setup and end state, explicit feed/power/dwell values, closed paths, cut ordering, agreement with the planned contours, stock-hole crossings, sheet boundaries and supported lead-in clearances. Failure for any used sheet prevents the complete plan from being accepted.

### Muse Code preparation boundary

Muse Code is used by the explicit scripts/prepare_postprocessor.py preparation workflow to draft a controller emitter. The candidate is tested against representative programs and final toolpath verification before its source and provenance are checked into backend/postprocessors/.

At runtime, postprocessor.py loads the prepared, checked-in emitter through a restricted interface. It does not accept arbitrary uploaded executable Python, and a live coding-agent call does not generate feed rates or controller code for each order. The normal job path compiles numeric geometry and verifies the emitted program deterministically.

verified_safe means that the final text passed the software checks for the supplied geometry, command subset and process values. It does not qualify the physical material, workholding, wiring, controller configuration or cutting process. The output uses centerline contours; kerf reserves spacing and estimated material loss but is not dimensional cutter compensation.

## Saved Plans and Cut-Confirmation Flow

    Order reviewed
      -> nesting + all sheet programs verified
      -> complete preview saved with plan ID and stock snapshot
      -> worker inspects layout and downloads exact programs
      -> physical cutting happens outside Remnant X
      -> worker explicitly records completion
      -> backend checks saved plan and current stock snapshot
      -> one SQLite transaction updates all affected remnants
      -> durable completion receipt returned

A partial layout can be inspected, but cannot be stored as a complete executable plan or used to update inventory. The frontend disables complete-order confirmation until all requested parts are placed and every used sheet has a verified program.

review_workflow.py stores the exact request identity, result, programs, consumed geometries and expected stock snapshots. Confirming a plan does not rerun nesting. db_and_parts.py checks that the current stock still matches the saved material, thickness and geometry, then applies every sheet update and writes a receipt in one SQLite transaction. A stale plan is rejected. Repeating a successful confirmation returns its existing receipt rather than consuming the same stock twice.

Remaining disconnected islands can become separate inventory records. Stock DXF references are cleared when the physical geometry changes. After a cut and physical rearrangement, the remaining pieces must be reindexed to refresh their photographed geometry.

The browser's download action is not a cut-completion signal. There is no machine connection or sensor feedback; the operator reports the physical action.

## Frontend Responsibilities

The React application is an interaction and visualization layer. It does not independently calculate the authoritative manufacturing layout or commit warehouse stock.

| Module | Responsibility |
| --- | --- |
| App.tsx | Navigation, Example/Live mode, backend status and inventory refresh |
| Scanner.tsx, Capture.tsx | Station setup, single-photo capture and preflight |
| PhotoBatch.tsx, photo-import.ts | Named photo/ZIP batches, limits, duplicate detection and per-photo progress |
| GeometryReview.tsx, PhotoRegion.tsx | Review outline, holes and selected image region |
| Inventory.tsx | Accepted stock, physical locations and stock labels |
| Plan.tsx, OrderEditor.tsx | Prompt/DXF intake, parts review, process settings and selected stock |
| CuttingPlan.tsx, SheetViewer.tsx | Sheet layouts, placements, toolpaths, verification and downloads |
| api.ts | HTTP boundary, JSON/multipart requests and error normalization |
| recovery.ts, station.ts | Browser-side recovery and station configuration |
| geometry.ts, verification.ts | Display-oriented geometry and result checks |

The Example mode reads a checked-in recording and image from public/example/. It is a synthetic, key-free walkthrough of a recorded result; it is not live SAM inference and does not require the backend. Live mode calls the API and reads the selected local warehouse.

## Communication Protocol

| Channel | Direction | Purpose |
| --- | --- | --- |
| HTTP JSON | Browser → FastAPI | Health, preflight, reviews, inventory, order parsing, nesting and confirmation |
| HTTP multipart | Browser → FastAPI | Vendor DXF upload |
| HTTP file response | Browser ← FastAPI | Indexed DXF artifact download |
| Provider HTTPS | Backend ↔ model provider | SAM segmentation and chat completion |

The frontend's api.ts prefixes requests with /api/v1/. In development, Vite proxies that path to the local API. There are no WebSocket messages, polling-based task events or public event bus. A request's response carries the result for that request; the browser's elapsed-time indicator is not backend progress telemetry.

The primary workflow endpoints are:

| Route | Purpose |
| --- | --- |
| GET /api/v1/health | API and configured-provider status |
| POST /api/v1/photo-preflight | Marker and calibration checks |
| POST /api/v1/index-remnant | SAM analysis and pending review creation |
| GET /api/v1/intake-reviews, GET .../{id} | Recover pending review results |
| POST /api/v1/intake-reviews/{id}/accept or /reject | Worker geometry decision |
| GET /api/v1/remnants, POST /api/v1/remnants | Query or explicitly insert stock |
| POST /api/v1/remnants/{id}/location | Update physical rack/location label |
| POST /api/v1/upload-dxf | Import a managed part definition |
| POST /api/v1/parse-order | Interpret a natural-language order |
| POST /api/v1/execute-pipeline | Nest, compile, verify and optionally save a plan |
| GET /api/v1/verified-plans/{id} | Recover the exact saved result |
| POST /api/v1/verified-plans/{id}/confirm | Confirm completion and update stock |
| GET /api/v1/artifacts/{filename} | Download a managed indexed DXF |

FastAPI publishes the request/response schema at /docs while the local service is running.

## Core Data Contracts

| Type / record | Meaning |
| --- | --- |
| StationImageRequest / IndexImageRequest | Image payload, measured station width/height, marker size and stock metadata |
| RemnantRecord | Physical stock identity, material, thickness, polygon, source and location |
| ManufacturingOrderSpec | Validated material, thickness, kerf and requested quantities |
| CADPartSpec | Part geometry, interior holes, quantity and grain restriction |
| PlacedPartInstance | One requested copy with its pose and transformed polygon |
| SheetNestingOutcome | Placements and remaining geometry for one remnant |
| BatchNestingResult | Multi-sheet result, requested/placed counts and search trace |
| CompiledSheetGCode | Final program, work origin, ordered loops and verification result |
| Intake review | Persisted analysis awaiting a worker geometry decision |
| FullPipelineRequest | Complete pipeline request, stock selection, search bounds, controller profile and process settings |
| Verified plan | Complete result and programs bound to a request and stock snapshots |

Shapely polygons represent the sheet exterior and its interior holes. SQLite stores stock polygon geometry as WKT; the serialization layer converts it into coordinate arrays for the browser. Image coordinates use X-right/Y-down; physical geometry uses millimetres with X-right/Y-up. The compiler records the work-origin translation used for each emitted program.

## State and Persistence

### Workflow states

    Remnant:
    photo -> preflight -> analysing -> pending review
                                  |-> accepted -> inventory
                                  -> rejected

    Manufacturing job:
    draft -> order review -> nesting -> partial / failed
                                    -> complete + verified
                                          -> saved plan
                                          -> operator confirms cut
                                          -> inventory transaction + receipt

These are product workflow states, not an asynchronous worker state machine. A scan or nesting request is handled within the API request. The persisted review and saved-plan records allow the browser to recover their exact results after reload without automatically repeating model inference or recomputing the plan.

### Durable and browser state

| Store | Data |
| --- | --- |
| SQLite warehouse | Accepted remnants, geometry, stock identity/material/thickness, pending intake reviews, saved verified plans and completion receipts |
| Managed artifact directory | Uploaded vendor DXFs and indexed/exported DXF files referenced by backend records |
| Browser IndexedDB | Original photo files and metadata used by the single and batch intake/recovery workflows |
| Browser localStorage | Station settings, workspace view/mode and live job drafts |
| Checked-in public/example/ | Synthetic example image and recorded result, independent of the live warehouse |

The database and artifact directory are one logical workspace: keep them together when moving or backing up a warehouse. Browser recovery also depends on the same browser origin. Clearing browser storage can remove unsent photo files; changing the database path selects a different inventory.

## Key Engineering Patterns

- **Human acceptance before inventory:** a segmentation result remains pending until a worker checks the overlay and accepts the geometry.
- **AI at bounded interfaces:** SAM supplies a mask; Muse Spark supplies an order extraction. Neither model is the source of truth for stock dimensions, legal placement or G-code safety.
- **Typed, guarded hand-offs:** request schemas, order-intent checks and managed DXF bindings validate data before geometry execution.
- **One geometry representation:** Shapely polygons retain boundaries and holes through stock selection, nesting and verification.
- **Independent placement sanitization:** candidate placements are checked against original sheet/part geometry, separate from the NFP proposal mechanism.
- **Verify emitted text, not only the plan:** the compiler reparses the final controller program and checks its supported motion semantics before it can be saved as complete.
- **Preview before mutation:** the desktop flow separates planning from cut confirmation; downloading a program does not alter inventory.
- **Atomic, replay-safe stock updates:** all affected sheets and the completion receipt are written together after stale-stock checks.
- **No silent substitution:** selected stock, material grades, thickness, managed files and incomplete plans are explicit constraints.

## Runtime Configuration and Validation

The backend reads provider credentials and workspace paths from its root .env file and environment variables. .env.example documents the supported names without containing credentials. The browser has no provider API keys. See [Local Startup](docs/LOCAL_STARTUP.md) for Windows/Python/Node setup and the supported launch commands.

The repository checks include an offline backend pytest suite and frontend Vitest/TypeScript/Vite checks. Live SAM smoke tests and provider benchmarks are separate, opt-in operations. Useful references:

- [Engineering guide](docs/ENGINEERING_GUIDE.md) — API contracts, supported DXF geometry and controller profiles.
- [Codebase guide](docs/CODEBASE_GUIDE.md) — file-by-file implementation details and trust boundaries.
- [Physical validation](docs/architecture/PHYSICAL_VALIDATION_20261030.md) — measured cardboard capture results and error.
- [Final readiness review](docs/FINAL_READINESS.md) — integration checks and known gaps.
- [Engineering Decisions](https://nikunjtrehan.github.io/remnant-x/engineering-decisions/) — recorded architecture choices and experiments.

## Scope and Limitations

Remnant X is a supervised prototype. Current validation used cardboard, not qualified production metal stock; the measured photo tests include a maximum exterior error of 7.32 mm on an oblique capture. Do not describe this as uniform millimetre accuracy or a production-qualified metrology system.

The nesting search is bounded and heuristic, not a proof of global optimality. DXF import supports a defined subset rather than arbitrary CAD. The two documented controller profiles do not imply compatibility with every CNC/laser machine. Output has no dimensional kerf compensation. No software check can verify physical workholding, machine setup, material condition or whether a cut actually occurred.

The operator remains responsible for checking the physical stock, reviewing the geometry, setting up the machine safely and confirming the completed cut. Remnant X records that human confirmation; it does not control the machine or sense the cut.
