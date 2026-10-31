# Remnant X codebase and architecture guide

Remnant X is a supervised local manufacturing prototype. It converts calibrated station photographs into reviewed remnant inventory, interprets a part order or imports vendor CAD, nests the required copies, and emits software-verified CNC centerlines. The worker remains responsible for geometry acceptance, physical stock identity, machine setup and reporting a completed cut.

This guide explains runtime files, data and trust boundaries, architectural choices, tests and practical limits. It is intended for a maintainer or reviewer who has not read the development conversations.

## How to read the repository

Start with README.md for the visible workflow, docs/LOCAL_STARTUP.md for setup, backend/api.py and backend/pipeline.py for the backend call chain, and Front End/src/App.tsx for navigation. Then follow the perception, interpretation, nesting and compiler modules below. docs/ENGINEERING_GUIDE.md defines the precise API, CAD and controller contracts.

The runtime is local and modular. Most geometry moves as Shapely polygons in memory. SQLite owns inventory, reviews and saved plans. The browser owns rendering, interaction and recoverable local files. Provider HTTP calls are confined to model-client modules.

## System responsibilities

| Layer | Responsibility | Durable state |
| --- | --- | --- |
| React and TypeScript | Capture, review, orders, batch choice and visualization | Browser drafts and original files |
| FastAPI | Strict inputs, managed uploads and workflow routes | Configuration references |
| Meta SAM 3.1 | Segmentation mask for a calibrated image | Saved optical review |
| Muse Spark Open | Natural-language order extraction | Accepted order and provider trace |
| Python geometry and compiler | Part construction, placement, sequencing and verification | Saved verified plan |
| SQLite | Accepted stock, pending reviews, snapshots and receipts | Selected local database |
| Artifact folder | Managed CAD uploads and indexed DXFs | Matching filesystem workspace |

## The photo to inventory workflow

The worker photographs one flat remnant inside a measured station. Four marker IDs and the measured black square size establish a planar reference. The frontend averages top/bottom and left/right station spans for the physical table dimensions sent to the backend.

Preflight detects markers and checks consistency before calling SAM. Missing or duplicate markers, invalid images or inconsistent calibration can block progress. A passed marker check is not an independent certificate of physical accuracy.

The indexer rectifies the image into the station reference. The SAM client sends the image and concept or region prompt to the actual Meta endpoint. It decodes the returned mask and validates the image/mask relationship. OpenCV performs marker detection, warping and vectorization; it does not secretly replace live SAM with threshold segmentation.

The mask becomes an outer material polygon with interior voids. The worker reviews the outline and holes over the image and must accept them before the piece becomes available inventory. Material, exact grade, thickness, ID and location are supplied explicitly. Segmentation does not identify alloy or thickness.

Each accepted batch photograph is saved independently. One rejected photo does not discard another accepted remnant. This intake behavior differs from the later atomic manufacturing transaction.

## The order to verified program workflow

A natural-language order includes quantities and supported dimensions or references an uploaded DXF. A short single-file request such as I want to cut 3 copies of this uses the visible DXF material, thickness and kerf choice. Multiple uploaded definitions can use explicit file-bound quantities in the parts list.

The intent checker rejects missing or contradictory requirements before accepting an extraction. Schema-valid model output is insufficient. A circle radius becomes twice that value as its diameter. Specific grades remain distinct from generic families and other grades.

The orchestrator constructs CAD parts and queries compatible stock. Selected batch IDs restrict the candidate set. It does not silently borrow an unselected sheet or substitute another grade. Candidates are ordered by usable area, smallest first.

The nester expands quantities, places parts against solid geometry and carries leftovers to later sheets. Larger part envelopes are attempted first; smaller items can backfill. Ring centers remain usable where the actual geometry permits it.

Every accepted placement passes separate coverage, stock-hole and part-clearance checks. NFP contact placement is the preferred proposal mechanism. If decomposition exceeds its budget, a disclosed bounded grid proposes alternatives against unchanged geometry. A missed placement means the search did not find one, not that no solution exists.

The compiler orders internal cuts before enclosing boundaries and emits controller text through a prepared emitter. The verifier reparses that final text and checks commands, process values, expected paths, inside-out order, stock holes and boundaries. A failed sheet prevents batch commitment.

A complete preview can be stored with its exact request identity, programs and stock snapshot. Cut confirmation uses that stored plan without renesting. Stock updates and the replay receipt commit together. Downloading or previewing a program does not report a physical cut complete.

## Why rotated stock matters

Calibration establishes scale, not axis alignment. The observed L-shaped specimen sits about 13.48 degrees from station XY. Searching only 0/90/180/270 degree part rotations produced a legal but incomplete three-copy layout.

Free parts now retain those orientations and also try the stock minimum-rotated-rectangle frame in quarter turns. Near-axis offsets below 0.1 degree are skipped. Grain-locked parts retain the existing station 0/180 restriction. Angle sets are cached per sheet.

On the accepted physical-photo outlines, the change placed one original-size decorative DXF on Piece B and two on Piece A. Both programs passed verification, with six and twelve loops, zero stock-hole crossing and zero outside-sheet path. Inventory was not changed. The decision is recorded in docs/architecture/ROTATED_STOCK_NESTING.md.

## Backend module reference

### HTTP boundary

**backend/api.py**

Creates FastAPI, a lazy warehouse and the provider client. Routes cover health, photo preflight, indexing and review, stock/locations, managed DXF upload, order parsing, execution, saved plans and confirmation. Uploaded files are validated before becoming order inputs. A short DXF request can carry explicit stock context from the UI. Routes translate known failures into HTTP responses; the geometric algorithms live elsewhere.

Key entry points: create_app.

### Public input contracts

**backend/schemas.py**

Strict Pydantic bodies describe station images, index requests, stock updates, natural-language/structured orders, process/search settings and confirmation. Unknown fields and non-finite numbers are rejected. Bounds constrain payloads, thickness, process inputs and search budgets. OrderStockContext supplies visible material, thickness and kerf; FullPipelineRequest can restrict execution to selected sheet IDs.

Key entry points: RequestModel, UpsertRemnantRequest, StationImageRequest, IndexImageRequest, StockLocationRequest, ConfirmCutRequest, OrderStockContext, NaturalLanguageOrderRequest, StructuredOrderRequest, FullPipelineRequest.

### Geometry response conversion

**backend/serialization.py**

Converts Shapely polygons, including interior holes, to browser coordinates, bounds and areas. It also serializes stock, placed instances, sheet outcomes and programs. This keeps HTTP routes independent of the representation details of Python geometry objects.

Key entry points: polygon_to_dict, dict_to_polygon, serialize_remnant, serialize_placed_part, serialize_sheet_outcome, serialize_compiled_gcode.

### Capture validation

**backend/photo_preflight.py**

Decodes the photograph, detects required markers and returns missing/duplicate IDs, consistency diagnostics and a rectified preview. Bad captures can be corrected before a paid SAM call. These tests establish input consistency, not independent proof that the segmented outline matches a physical sheet.

Key entry points: decode_station_image, photo_preflight.

### Calibration and optical indexing

**backend/m1_sam_indexer.py**

Defines station and calibration types and the optical indexer. Four identified ArUco markers and their corners establish a planar homography. Coordinates are mapped to millimetres and marker-scale consistency is checked. The normal live path obtains a SAM mask and vectorizes outer/inner contours. Explicit local thresholding retains separate demo provenance. Optional CLAHE changes lighting input rather than replacing segmentation.

Key entry points: StationCalibrationConfig, CalibrationReport, IndexedRemnantResult, RemnantOpticalIndexer.

### SAM transport and mask decoding

**backend/sam_client.py**

Calls the Meta Responses endpoint with the configured SAM model, image and concept/region prompt. meta-sam-parser decodes the actual model output into a raster mask. Response image dimensions, selected object, bounds and nonempty content must agree. Missing matches or malformed output are failures requiring attention, not permission to invent geometry.

Key entry points: decode_image_output, segment_image.

### Provider transport

**backend/llm_client.py**

Reads backend environment configuration and implements Baseten, Fireworks and Meta chat transport. The normal order route prefers Baseten Muse Spark Open with configured failover. The client returns provider/model, latency, usage and output to the orchestrator. Keys stay on the backend. A transport success cannot approve a manufacturing order or placement.

Key entry points: LiveModelClient.

### Exact material identity

**backend/materials.py**

Normalizes family and grade aliases while preserving ss304, ss316, al6061 and al5052 as distinct identities. Unknown labels remain distinct. Explicit prompt identities are compared with interpretation. Cardboard is an explicit demonstration material. This is conservative matching, not an alloy-equivalence database or physical composition measurement.

Key entry points: normalize_material, material_identity, explicit_prompt_materials.

### Request grounding

**backend/order_intent.py**

Checks supported names, quantities, dimensions, units, thickness, kerf and file references. Missing/contradictory inputs stop acceptance. Circle radius becomes diameter; equivalent parenthesized units are accepted only when consistent. A single uploaded file can be referenced as this or it. The model extraction must match the explicit request. This is a bounded consistency grammar, not unrestricted English understanding.

Key entry points: clarify, millimeters, quantity, dimensions, labelled_dimension, normalize_equivalent_units, circle_diameter, inspect_order_prompt, signature, check_order_intent.

### Orders and stock candidates

**backend/m2_spark_orchestrator.py**

Defines requested parts, validated orders and orchestration plans. It parses model/structured data, binds only managed DXFs, creates CAD specifications and matches exact material/thickness. One configured Fireworks repair can correct a rejected complete extraction, subject to the same guards. Cloud failure can invoke a limited millimetre-only deterministic parser. Candidate stock is returned in smallest-usable-area order.

Key entry points: RequestedPartItem, ManufacturingOrderSpec, OrchestrationPlan, SparkWarehouseOrchestrator.

### Warehouse and CAD factory

**backend/db_and_parts.py**

Stores stock as WKT in SQLite, queries compatibility and applies all-sheet cuts transactionally against expected geometry/identity snapshots. Disconnected leftover islands become separate records; outdated DXF references are cleared. CADPartFactory creates supported parametric shapes and reads/writes DXFs. Import checks declared units, closed planar contours, hole containment and vertex bounds. Accepted uploads become canonical millimetre polylines so downstream stages use exactly the reviewed approximation.

Key entry points: RemnantRecord, CADPartSpec, RemnantWarehouseDB, CADPartFactory.

### Placement and bounded search

**backend/m3_nfp_nester.py**

Computes no-fit polygons from convex pieces while preserving meaningful voids. Quantities expand into instances. Larger envelopes start first; failed instances spill to later sheets while smaller parts backfill. Seeded local annealing can explore part-order changes within worker/iteration budgets. Free rotations include the station and sheet frames; grain locks preserve 0/180. Complexity overflow uses a disclosed bounded grid. Independent placement checks still use original stock and part polygons.

Key entry points: convex_pieces, no_fit_polygon, vertices, PlacedPartInstance, SheetNestingOutcome, BatchNestingResult, HoleAwareNester.

### Compilation and verification

**backend/m4_muse_gcode.py**

Orders nested/internal cuts before enclosing contours and constructs numeric paths and optional bounded lead-ins. Prepared emitters format controller text. The verifier reparses the final text and checks commands, process values, paths, inside-out order, stock-hole crossings and sheet bounds. Verified output means planned centerlines passed software checks; it does not establish physical accuracy, dimensional kerf compensation or a qualified laser process.

Key entry points: arc_points, CutLoopSegment, GCodeVerificationReport, CompiledSheetGCode, GCodeCompiler.

### Prepared emitter contract

**backend/postprocessor.py**

Loads supported checked-in GRBL/LinuxCNC emitters and validates a narrow Python AST: one bounded loop over typed blocks, restricted formatting and no uploaded executable code. The code converts numeric programs to emitter input and records source identity. Muse Code operates in preparation, not once per job. Every emitted program still passes the final verifier.

Key entry points: validated_emitter, render_emitter, program_to_job, emit_prepared.

### Manufacturing orchestration

**backend/pipeline.py**

Resolves input and managed uploads, loads stock, applies selected-sheet restrictions, nests, compiles and verifies every used sheet. Preview results include counts, candidates, placements, programs, search trace, timings and measured utilization. Complete plans can be saved with request/stock identities. No sheet is committed before all sheet programs pass. Partial batches cannot commit. The explicit legacy direct-commit API remains separate from the UI confirmation workflow.

Key entry points: checked_uploads, check_order_uploads, execute_pipeline.

### Reviews and exact-plan completion

**backend/review_workflow.py**

Persists optical results and supports recovery, acceptance and rejection. A successful analysis is not inventory until accepted. Saved plans bind a program to its job and stock snapshot. Confirmation applies stored cuts rather than renesting; a replay receipt prevents duplicate completion. Changed geometry, material, thickness or provenance blocks a stale update. The transaction commits all updates and the receipt together.

Key entry points: get_review, cached_review, save_review, pending_reviews, accept_review, reject_review, get_plan, save_plan, confirm_plan.

### Python package boundary

**backend/__init__.py**

Marks the backend package. It does not launch a server or seed inventory.

## Controller profile files

**backend/postprocessors/grbl.py** formats the supported GRBL laser profile from typed job blocks. **backend/postprocessors/linuxcnc.py** formats LinuxCNC output. Preparation manifests record emitter identity. These are checked-in prepared assets, not arbitrary user-uploaded postprocessors. The common verifier checks final emitted text.

## Frontend file reference

**Front End/src/main.tsx**

Mounts React and shared styling. StrictMode remounts in development must not overwrite a saved draft.

**Front End/src/App.tsx**

Owns Plan/Scan/Inventory navigation, live/example mode, health/inventory refresh and recorded example loading. A fresh browser can open the labeled Example; choose Live workspace for real work.

**Front End/src/Scanner.tsx**

Selects single-photo or batch/ZIP intake and shares the persisted station profile. Both modes use the same backend preflight, SAM and review contracts.

**Front End/src/Capture.tsx**

Runs a selected photo through station setup, region selection, preflight, SAM, recovery and geometry review. Material, thickness, stock ID and location are explicit inputs.

**Front End/src/PhotoBatch.tsx**

Maintains named batches and per-photo state. It handles ZIP/loose-file import, shared defaults, checks, sequential analysis, per-photo errors, explicit retry, recovery and accepted stock. Each photo is reviewed separately.

**Front End/src/photo-import.ts**

Validates JPEG/PNG and ZIP inputs, count/size limits and duplicate bytes. Expanded images are bounded; a renamed image is not new physical stock.

**Front End/src/GeometryReview.tsx**

Shows the pending outline/holes and requires confirmation before stock acceptance. It exposes rejection and label actions. Analysis success alone does not make a sheet available.

**Front End/src/PhotoRegion.tsx**

Selects a region in the rectified image to target SAM. The box is a model prompt, not a hand-drawn replacement contour.

**Front End/src/Plan.tsx**

Owns prompts, structured parts, DXF upload, stock/batch selection, visible stock context, order review, invalidation, execution and confirmation. Uploaded quantities stay synchronized with the reviewed file-bound order.

**Front End/src/OrderEditor.tsx**

Edits interpreted material, thickness, kerf, quantities and supported shape dimensions. The worker can correct an extraction or use explicit CAD-bound parts before nesting.

**Front End/src/CuttingPlan.tsx**

Displays counts, sheet tabs, allocation order, part inspection, planned paths and verification. It gates downloads/completion by plan state. Playback is a visualization, not machine-physics simulation.

**Front End/src/SheetViewer.tsx**

Renders material, holes, placements, kerf zones and paths as SVG in millimetres with selection and zoom. It draws server results rather than nesting parts in JavaScript.

**Front End/src/Inventory.tsx**

Shows accepted stock, locations and labels so a worker can identify the physical sheet associated with a plan.

**Front End/src/recovery.ts**

Stores original photos/batch metadata in IndexedDB and the job draft in localStorage. Namespaced batches preserve separate queues. Recovery does not automatically restart SAM; backend reviews and stock remain authoritative.

**Front End/src/api.ts**

Centralizes HTTP errors, station payloads, multipart DXF upload and API calls. Stock context and selected IDs cross this boundary; provider credentials do not.

**Front End/src/types.ts**

Defines TypeScript contracts for geometry, stock, orders, uploads, station setup, reviews, placements, programs and pipeline results.

**Front End/src/verification.ts**

Requires consistent complete placement counts, no unplaced instances, sanitizer approval and a verified program for every used sheet. The badge reflects these conditions.

**Front End/src/geometry.ts**

Builds SVG paths and readable dimension/part labels. Display formatting does not modify manufacturing geometry.

**Front End/src/station.ts**

Defines and validates the shared station profile. Current defaults describe this measured test station, not every workshop.

**Front End/src/stock-label.ts**

Generates an SVG stock ID/location label connecting a database item to a physical piece.

**Front End/src/errors.ts**

Maps backend error codes to worker guidance and support details for capture, provider, geometry, duplicate and stale-state failures.

**Front End/src/ui.tsx**

Provides reusable fields, modals, busy indicators, error notices and validated local-state loading.

**Front End/src/ExampleTour.tsx**

Explains the labeled recorded example in guided chapters without pretending that live inference ran on page load.

**Front End/src/styles.css**

Defines the desktop visual system, shell and layout.

**Front End/src/planning.css**

Styles the parts editor, spatial workspace and planning controls.

**Front End/src/workflows.css**

Styles workflow, review and inventory panels.

**Front End/src/intake.css**

Styles photo queues, batch history, stock choice, DXF context and allocation summaries.

**Front End/src/example.css**

Styles the recorded example and tour.

## State and recovery contracts

SQLite contains remnants, intake_reviews and verified_plans. Stock includes material, thickness, WKT geometry, areas, holes, provenance, CAD reference and location. Optical reviews retain geometry and image/frame information. Plans retain exact programs, expected stock identities and consumed geometry.

The artifact folder is paired with the selected database. Managed CAD is stored as the reviewed millimetre polylines; indexed DXFs are downloadable. Database references remain meaningful only while the corresponding files remain available.

IndexedDB stores photo originals/batch metadata; localStorage stores station/view/order convenience state. Another browser or port can show different history even when it uses the same warehouse. A new database can be empty while older browser drafts exist. These are different state stores.

Duplicate protection recognizes exact image bytes. Another photograph of the same physical sheet is not automatically recognized as duplicate stock. Use the ID written on the sheet and operator discipline.

## Architectural decisions

| Decision | Reason | Boundary |
| --- | --- | --- |
| Models interpret and geometry decides | AI perceives images and extracts requests; ordinary code handles iterative placement and checks | A correct path can still follow an incorrect mask; review is required |
| Prepare emitters outside the job loop | Reuse reviewed controller formatting without a coding-agent call per job | Only explicit prepared profiles are claimed |
| Measured ArUco station | Stable identified corners establish a planar reference | Flat setup, correct dimensions and visible markers are required |
| Holes are actual topology | Scrap is solid material with voids, not a bounding box | Uncertain or invalid topology must be reviewed/rejected |
| Exact grades and thickness | Prevent silent material substitutions | No alloy equivalence or physical identification database |
| Smallest usable stock first | Use remnants before unnecessarily consuming large sheets | No global stock-selection optimum |
| Skip and backfill | A failed large part should not block smaller useful parts | Placement/order choices affect utilization |
| Reuse ring centers | Preserve usable inner material where geometry allows | Workholding and physical cutting need qualification |
| Sheet-aligned free rotations | Image orientation should not suppress valid placements | Finite angles; grain locks remain explicit |
| Bound search complexity | Avoid unlimited decomposition/calculation | A bounded search can miss a legal packing |
| Review before availability | Segmentation is a candidate observation | Worker approval is required |
| Store the exact verified plan | Confirmation must not silently produce a different cut | Changed stock requires a new reviewed plan |
| Verify all sheets before commit | Prevent partial warehouse corruption | Partial previews cannot commit a full order |
| Preserve demonstration provenance | Sample material must not become real inventory silently | Demo/local stock needs explicit opt-in |
| Named batch history and selection | Repeated ZIP deliveries remain distinct and selectable | Browser history differs from warehouse state |
| SQLite and in-memory polygons | Keep the local system traceable and easy to run | No distributed multi-tenant production service |
| Measure provider routing | Historical primary-first median was 3.23 s versus 18.73 s for parallel agreement | Historical benchmark is not a score for the latest guarded parser |
| Grounded Fireworks repair | Recover a rejected complete extraction where possible | Repair passes the same deterministic checks |
| Optional CLAHE | Measure whether lighting normalization helps | No guarantee against glare or distortion |
| Measured utilization and timings | These are observable run properties | Money/CO2 savings need equivalent-production baselines |
| Physical SOPs and experiments | Capture, identity and handling affect correctness | Cardboard does not qualify reflective metal or machines |
| Labeled recorded example | Reviewers can inspect the core workflow without keys | Stored output remains separate from live inference |
| Public decision website | Keep alternatives, rationale, evidence and limits reviewable | Preserve historical experiment dates and scope |

The hot/cold-path inspiration was discussed as a pattern borrowed from Recover AI. Here it separates model interpretation and offline compiler preparation from repeated numeric work. SAM and order parsing still make interactive cloud calls.

## Dependencies and configuration

**requirements.txt** pins FastAPI/Uvicorn, Pydantic, multipart handling, dotenv, NumPy/OpenCV, Shapely, ezdxf, HTTPX and the SAM parser. **requirements-dev.txt** adds offline test dependencies. Use the project virtual environment.

**.env.example** documents model endpoints, names and storage settings without real credentials. **.env** is local and ignored. Process environment can select another workspace. Provider keys must never enter a frontend build.

**Front End/package.json** defines dev, test, build and check commands. **package-lock.json** locks dependencies for npm ci. **vite.config.ts** configures React, tests, a strict dev port and /api proxy to port 8000. That proxy is not included in the production build.

**Front End/tsconfig files** define TypeScript compilation. **Front End/index.html** is the browser entry. **Front End/public/example** contains labeled synthetic example inputs and backend outputs.

**.gitignore** excludes secrets, environments, databases, raw local artifacts, node_modules, generated builds and private handoffs. **.gitattributes** controls text/binary handling. **LICENSE** states the repository license; external uploaded artwork retains its own rights.

## Scripts and benchmarks

**scripts/start.ps1** launches the API from the root, supports a port and separate demo storage, and never seeds stock. It does not enable autoreload.

**scripts/smoke_sam.py** is an opt-in live connectivity test that may spend provider credits. It is not part of normal offline regressions.

**scripts/prepare_postprocessor.py** uses the separate Muse Code preparation workflow and records emitter identity. Prepared source and emitted programs must satisfy the common contracts.

**scripts/record_frontend_example.py** records the demonstration using the actual backend workflow rather than a fabricated result/progress sequence.

**benchmarks/order_interpretation.py** defines representative cases and evaluates policies against frozen expectations. **benchmarks/render_report.py** produces the readable report. **benchmarks/README.md** describes reproduction. Normalized summaries and compressed full evidence are preserved under docs/architecture.

The original benchmark used 20 prompts, three repetitions and two policies: 120 trials. It observed 50/60 correct baseline outcomes versus 51/60 for mandatory parallel agreement, with higher parallel latency/cost. Missing-input and contradiction weaknesses were guarded afterward. These original numbers remain historical evidence, not a fresh accuracy measurement of the current parser.

## Backend regression map

**backend/tests/conftest.py**: Keeps the regression environment deterministic and offline.

**backend/tests/test_api_server.py**: HTTP route contracts and application behavior.

**backend/tests/test_batch_stock_selection.py**: Selected stock restrictions, no borrowing unselected inventory and changed-selection replay protection.

**backend/tests/test_dxf_copy_prompt.py**: Upload-to-order quantities, this/it references, visible stock context, offline parsing and conflicting settings.

**backend/tests/test_module0_db.py**: Warehouse persistence and inventory operations.

**backend/tests/test_module1_calibration.py**: Calibration and coordinate conversion.

**backend/tests/test_module2_filter.py**: Material/thickness filtering and candidate stock ordering.

**backend/tests/test_module3_nester.py**: Hole clearance, grain locks, ring centers, backfill, spillover and complexity fallback.

**backend/tests/test_module4_gcode.py**: Cut order, toolpaths and final-program verification.

**backend/tests/test_nfp_search.py**: NFP membership against independent intersections, hollow centers, reproducibility and rotated-stock placement.

**backend/tests/test_orchestrator_and_indexer.py**: Order/indexer behavior with controlled providers.

**backend/tests/test_order_intent.py**: Frozen benchmark cases, missing/conflicting inputs, extraction changes, circle radius and equivalent units.

**backend/tests/test_phase_b_full_integration.py**: Integrated geometry-to-output behavior.

**backend/tests/test_photo_preflight.py**: Marker/capture failures and preflight without paid perception.

**backend/tests/test_promise_acceptance.py**: Promised batch workloads, many distinct uploaded parts, holes and verified output.

**backend/tests/test_promised_execution.py**: Prepared controller contracts and execution promises.

**backend/tests/test_review_workflow.py**: Review acceptance, saved-plan recovery, confirmation receipts and stale-state protection.

**backend/tests/test_safety_regressions.py**: Atomic rollback, unknown commands, material grades, managed uploads, SAM contracts and provenance.

**backend/tests/test_vendor_curves.py**: Declared units, closed splines, five holes, canonical uploads, invalid 3D/open curves and smallest-first spillover.

## Frontend regression map

Component tests cover navigation/example isolation, station setup, capture, ZIP/history/retry/reload recovery, stock selection, order review, DXF context/quantities, sheet-specific artifacts, geometry display and region selection. FactoryWorkflow.test.tsx exercises cross-component guards. recovery.test.ts and photo-import.test.ts independently check persistence and intake limits. test-setup.ts controls the browser test environment.

A production build checks TypeScript and bundles the application. Passing tests do not qualify a physical camera measurement or cutting machine.

## Documentation and publication files

**README.md** is the reviewer entry point for product visuals, setup, responsibilities, evidence and limits. **docs/LOCAL_STARTUP.md** explains operation. **docs/CODEBASE_GUIDE.md** is this reference. **docs/ENGINEERING_GUIDE.md** defines precise contracts.

**Front End/WORKFLOW_GUIDE.md** covers worker recovery and review. VALIDATION.md, FACTORY_SCENARIOS.md and MILESTONES.md record frontend evidence, scenarios and development stages. Repository presentation research is recorded under docs. **docs/FINAL_READINESS.md** preserves a dated integration review.

**docs/architecture/index.html** is the static decision site. DECISION.md and benchmark JSON record routing policy. FACTORY_REVIEW.md explains approval and confirmation boundaries. ROTATED_STOCK_NESTING.md records the rotation fix. Physical-validation reports preserve two cardboard experiments and ground-truth corrections. Application-promise/repository audits retain their original dates and scope. Public fixtures/assets are separate from private customer uploads.

**docs/REPOSITORY_PRESENTATION_RESEARCH.md** records inspected winner repositories and the evidence behind presentation recommendations. **.github/workflows/checks.yml** runs offline backend tests and frontend checks. **.github/workflows/pages.yml** publishes checked-in documentation. The static site does not host FastAPI or expose local keys/databases.

## Verification and practical limits

The actual three-copy physical-photo run placed one decorative part on Piece B and two on Piece A, with both final programs verified. The offline and frontend suites check software contracts, not factory certification.

Physical validation covers two cardboard specimens and eight captures: five usable topologies and three blocked captures. Exterior error reached 7.32 mm. Some ruler references were corrected after seeing outputs; preserve that fact in the evidence. Do not claim uniform millimetre accuracy or model-blind independent validation.

The prototype does not provide automatic material identification, full lens/camera certification, reflective-metal qualification, arbitrary industrial DXF or controller support, dimensional kerf compensation, fixturing qualification, machine connectivity or physical cut sensing. It is a supervised local workflow.

Search orientations, ordering, iterations and fallback sampling are bounded. A missed placement is not an impossibility proof. Utilization does not establish lower cost or CO2 without a measured equivalent-production baseline.

## Extending the system

Add CAD support at the import boundary, state units/approximation, canonicalize reviewed geometry and test topology. Add controllers only through explicit emitter/profile contracts and final verification. Add providers where perception/interpretation has a measured purpose.

Preserve exact grade matching, geometry approval, request binding, stale-state checks and atomic confirmation. Never make model prose a source of unqualified process settings. Keep unsupported cases visibly unsupported.

Run backend tests from the root and npm run check from Front End. Keep physical experiments and opt-in network benchmarks outside offline CI. Use reviewable commits and protect .env, databases, photos and artifacts before publishing.

Architectural decisions: https://nikunjtrehan.github.io/remnant-x/architecture/

Repository: https://github.com/nikunjtrehan/remnant-x
