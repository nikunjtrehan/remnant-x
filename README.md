# Remnant X

Desktop workbench and backend prototype for photo → remnant inventory → manufacturing order → nesting → verified G-code. Meta SAM 3.1 supplies segmentation; model-assisted order parsing supplies structured requests; local geometry decides placement and verifies the generated program.

## Desktop workbench

The frontend lives in [Front End](Front%20End/README.md). It provides a recorded
synthetic example with a guided visual walkthrough, a photo/scanner gate,
inventory inspection, editable order review, multi-DXF quantities, per-sheet
nesting views and verified downloads. Example mode never substitutes for a live
request. The example uses actual offline backend output, not a live SAM result.

Start the API using the Windows instructions below. In a second terminal, from
the project root:

```powershell
Set-Location 'Front End'
npm ci
npm run dev
```

Open the printed local address, normally **http://127.0.0.1:5173**. Both processes
must be running for live work. The recorded example works with the frontend alone.
Provider credentials remain on the backend. Use Node 22.12 or newer.

Frontend changes were developed as four local milestones; see the
[milestone record](Front%20End/MILESTONES.md) and
[validation notes](Front%20End/VALIDATION.md). The live inventory-update action is
explicitly a replan followed by an atomic predicted-stock update; it does not
claim to commit exactly the earlier preview or operate a machine.

Read `backend/api.py` for HTTP routes and `backend/pipeline.py` for the manufacturing workflow. Public request types live in `schemas.py`; geometry/result conversion lives in `serialization.py`. The numbered modules retain the optical, order, nesting and G-code stages. The implemented classes are `HoleAwareNester` (NFP contact placement plus bounded simulated annealing) and `GCodeCompiler`; old Python names remain compatibility aliases. Baseten is the default order parser; Fireworks supplies transport failover and one guarded repair of a rejected complete-order extraction. Independent local nesting searches run in parallel; no three-cloud blackboard sits in the execution path.

The [application promise audit](docs/architecture/APPLICATION_PROMISE_AUDIT.md) records the recovered application wording, implementation evidence and outstanding commitments. The backend now includes parallel NFP/annealing search, real Muse Code-prepared emitters and optional checked arc lead-ins. The [repository audit](docs/architecture/REPOSITORY_AUDIT.md) explains the winner-source review, simplifications and remaining limits. The [physical validation protocol](docs/architecture/PHYSICAL_VALIDATION.md) separates routine photo indexing from independent ruler measurements used only for testing.

## Start on Windows

Use Python **3.11**. From the project root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\scripts\start.ps1 -Demo
```

An existing `.venv` can be reused; skip creating it in that case. `requirements.txt` contains runtime dependencies; `requirements-dev.txt` adds pytest. If PowerShell blocks scripts, use the equivalent commands below. These are project commands, so they do not require changing machine execution policy.

```powershell
$env:REMNANTX_DB_PATH = 'demo_warehouse.db'
$env:REMNANTX_ARTIFACT_DIR = 'artifacts\demo'
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/docs**. The demo database starts empty. Use `POST /api/v1/seed-demo-warehouse` explicitly to add synthetic stock. Reseeding resets only the three `DEMO_` records. No startup code seeds inventory.

`start.ps1` without `-Demo` uses `REMNANTX_DB_PATH` if set, otherwise `warehouse.db`. Restart in a fresh shell or unset that variable when switching away from the demo database. API imports do not initialize SQLite; the first warehouse operation does. Existing databases receive a `source` column without deleting rows.

Copy `.env.example` to `.env` **only when creating a new configuration**. Preserve an existing `.env`. Set `META_API_KEY` for real SAM. Baseten, Fireworks and Meta chat credentials are optional for model-assisted order parsing. A health check reports configured credentials, not successful connectivity. Modal is not required for this SAM implementation.

## Demonstrate the complete order pipeline

After explicitly seeding demo stock, submit this to `POST /api/v1/execute-pipeline`:

```json
{
  "order": {
    "order_id": "DEMO_JOB_01",
    "material": "steel",
    "thickness_mm": 3,
    "kerf_mm": 1,
    "parts": [{"part_id": "DISC", "shape_type": "circle", "diameter_mm": 20, "quantity": 5}]
  },
  "allow_demo_stock": true,
  "machine_profile": "ISO_6983_GRBL",
  "commit_cuts_to_db": false
}
```

Preview first. `commit_cuts_to_db=true` deliberately changes the inventory to the predicted post-cut geometry; it does **not** execute a machine or confirm a physical cut happened. A partial order cannot commit. All sheets must compile and pass verification before one SQLite transaction changes any stock. A stale geometry, material, thickness or provenance snapshot rejects the transaction. Disconnected remaining pieces receive separate inventory records; old DXF references are cleared because those files no longer describe the stock. Reindex pieces after they move.

The returned `verified_safe` means the emitted command subset and planned centerline geometry passed the software checks. See the process limitations below before using output on equipment.

## Upload a vendor DXF and make 50

1. Use `POST /api/v1/upload-dxf` in Swagger and choose the vendor file. Copy the returned `dxf_path`.
2. Use `POST /api/v1/parse-order` with a prompt such as `Cut 50 of the uploaded dxf file from 3mm ss304 sheet, kerf 1mm` and `uploaded_dxf_files: ["<returned dxf_path>"]`.
3. Review the returned dimensions, material, quantity and DXF binding. Submit the returned `order` to `/api/v1/execute-pipeline`. The structured order already includes its DXF path.
4. The warehouse must contain compatible **ss304**, 3 mm stock with sufficient space. Generic demo steel is deliberately incompatible. An upload creates a part definition, not sheet inventory.

An uploaded DXF can also be bound directly using a structured part: `{"part_id":"VENDOR", "shape_type":"dxf_file", "quantity":50, "dxf_path":"<returned path>"}`. For multiple uploads, use explicit paths in a structured order. API paths must stay inside the managed upload directory. Uploads are limited to 5 MB and stored under generated names.

**Accepted DXF contract:** one planar outer boundary plus zero or more disjoint holes, represented by closed, straight `LWPOLYLINE` entities. `$INSUNITS=4` means millimeters; unitless files are explicitly interpreted as millimeters. Circles, arcs, bulges, open loops, blocks, text, splines, other units, tilted/extruded contours, multiple outer boundaries and nested/overlapping holes are rejected. Export curves as sufficiently fine straight polylines in your CAD tool. Exports produced by this application explicitly declare millimeters.

## Real SAM and the ArUco station

`POST /api/v1/index-remnant` defaults to `segmentation_mode="sam"`. It sends the rectified PNG to Meta's **`POST /v1/responses`, model `sam-3.1`**, consumes SSE output and decodes masks with the official `meta-sam-parser`. Chat completions and OpenCV thresholding do not supply the SAM mask.

Set `segmentation_concept` to a short phrase such as `cardboard sheet`. If a concept does not identify the intended object, use `segmentation_box_px: [left, top, right, bottom]` instead. Box coordinates refer to the **rectified, cropped station image**, X right/Y down, with right and bottom exclusive. At the default scale that image is 1200 × 900 pixels. The box prompt replaces the concept in the request. `segmentation_object_id` can select a specific returned object; ambiguous or empty results fail instead of becoming an arbitrary largest mask.

Missing credentials, incomplete streams, bad dimensions, malformed masks and disconnected stock fail indexing. There is no automatic local fallback. Holes are retained without a default area filter or morphological closing. Vector coordinates use millimeters with X right/Y up. `camera_angle_deg` is null: camera intrinsics are required to establish a physical viewing angle. The marker residual is an internal calibration consistency check, not independent physical ground truth.

For an explicit local demo use `segmentation_mode="local_threshold"`. This source persists in SQLite and requires `allow_demo_stock=true` during pipeline execution, just like seeded demo stock. `use_clahe=true` enables optional LAB luminance normalization. CLAHE is off by default; improvement must be established with paired measurements on the actual station. Surface-model advice remains advisory.

An explicit live connectivity smoke test uses a synthetic image and never changes inventory:

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_sam --synthetic --box 125 95 536 396
```

For an image you supply, use `--image path.png --concept "cardboard sheet"`, optionally with `--box`. This command sends the selected image to Meta and uses API credits.

### Physical acceptance test still required

Use your real printed station and measured cardboard. Keep the sheet flat and markers visible. Capture outer dimensions and every hole with a ruler or caliper, then index the same sheet at several positions and lighting conditions. Compare extracted widths, heights, hole count, hole dimensions and boundary overlays with the measurements. Repeat the exact frames with CLAHE on and off. Record the errors and set a suitable acceptance threshold for the machine and material before claiming physical accuracy. Current automated tests establish synthetic geometry and transport correctness; they do not certify your physical station.

## Material and controller boundaries

Material identity is exact: `ss304`, `ss316`, `a36`, `al6061`, `al5052`, `stainless_steel`, `mild_steel`, `carbon_steel`, `steel` and `aluminum` remain distinct. Unknown material/grade labels stay distinct instead of being reduced to a familiar family. Thickness matching defaults to ±0.01 mm. A grade explicitly requested in a prompt cannot be downgraded by the model. Missing or contradictory inputs require clarification before a model call; a rejected complete extraction can receive one Fireworks repair, which must pass the same checks. Material grades already lost by an older version cannot be recovered automatically; relabel or reindex that stock using its actual specification.

Implemented profiles are **ISO_6983_GRBL** (GRBL 1.1 laser mode) and **LINUXCNC_LASER** (operator-qualified M3/M5 laser mapping). They use real Muse Code-prepared emitters stored with provenance in `backend/postprocessors/`. LinuxCNC establishes G61 exact-path mode and uses M2 program end. The bounded command set includes `G21`, `G90`, `G94`, `G17`, `G91.1`, `G61`, `G00`, `G01`, `G02`, `G03`, `G04`, `M03`, `M05`, `M2`, `M30`. G94 explicitly establishes feed per minute. The verifier rejects unsupported opcodes and parameters, malformed/duplicate words, active-laser rapids, missing setup/end state, open contours, and cuts differing from the planned sequence. It checks the exact final postprocessed text before export/commit. Proprietary controller names, including Fanuc and Trumpf, fail with an unsupported-profile error. A requested quarter-circle lead-in must fit in waste, clear of stock holes and other parts; an unsafe request fails. Lead-in footprints and kerf are subtracted from predicted stock in the original inventory coordinate frame.

Output uses **centerline contours**. Kerf reserves placement clearance and predicted stock loss; it does not implement dimensional cutter compensation. The operator must qualify feed, power and dwell for the actual machine/material, configure GRBL `$32=1` and `$30=1000`, and establish the work origin at the reported physical sheet vertex. These settings are documented prerequisites, not machine configuration performed by the API. The application does not validate hold-downs, lens distortion, Z clearance, gas systems, thermal effects or cut completion. No machine is connected or run by this backend.

## Search, lead-ins and prepared emitters

`execute-pipeline` accepts `search_iterations` (default 2 per chain, 0..100),
`search_workers` (default 2, 1..4) and `search_seed` (default 17). Identical-shape
orders or disabled annealing use one search rather than duplicate work. The response
records actual workers, evaluated layouts and whether the result is globally optimal
(always false). Legacy `coarse_step_mm` / `fine_step_mm` remain accepted for old
clients but do not control NFP placement.

Set `lead_in_radius_mm` above zero to request quarter-circle pierce approaches;
the default is zero. `cut_feedrate_mm_min`, `laser_power_s` and `pierce_delay_sec`
are explicit process inputs. Defaults are demonstrative settings, not recommendations
for a material or machine. Final verification checks the configured values as well
as coordinates. Arcs are limited to XY centre format with incremental I/J and
sweeps up to 180 degrees; their conservative sampling envelope is checked too.

The shipped emitters were generated by real Muse Code and validated. They need no
live coding agent at backend startup or per job. To prepare a replacement deliberately
(uses Meta credits and requires the official Muse Code CLI):

```powershell
.\.venv\Scripts\python.exe -m scripts.prepare_postprocessor --profile ISO_6983_GRBL --muse <absolute-path-to-muse.exe>
```

Only the restricted emitter contract is accepted; final programs must still pass
verification. There is no endpoint that executes uploaded Python. Set
`REMNANTX_ORDER_PROVIDER=meta` to use Muse Spark 1.3 directly for order interpretation,
or retain the default `baseten` for Muse Spark Open. Stock filtering remains local
and authoritative. The original one-million-token inventory-prompt proposal was
not adopted; the reason and exact deviation are recorded in the application audit.

## Timings, metrics and tests

Responses contain measured stage times, counts, input usable area, placed solid area and area utilization. Financial and CO₂ savings are null until there is a measured equivalent-production baseline, procurement prices and explicit lifecycle assumptions. A fast result or high packing utilization does not supply those assumptions. Nesting uses NFP contact placement and seeded parallel simulated annealing, not a proof of global optimality. GEOS uses double precision. NFP work is bounded to 4,096 vertices per decomposition, 20,000 convex pairs and 500,000 edge operations; excessive complexity fails explicitly.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The test suite disables cloud credentials inside the test process. It includes geometry, second-sheet verification failure, final-program tampering, actual SQL rollback, stale plans/materials, disconnected stock, grade separation, DXF rejection, upload-to-50-parts, SAM wire decoding, interrupted streams, synthetic photo dimensions and persisted demo/local provenance. The live SAM smoke test is separate and opt-in.

**Backend milestone validation:** 81 tests passed. A separate live SAM box-prompt check returned a decoded mask, and local server startup was exercised with disposable demo inventory. Physical station accuracy and real-machine process qualification remain pending.

**Local validation on 29 October 2026:** 164 tests passed. Coverage includes 101 distinct uploaded synthetic DXFs in one verified order, a separate 105-instance mixed batch, parallel search, both prepared emitters, arc/process tampering, lead-in inventory coordinates and atomic rejection. The 101-file test took about 60 seconds including file generation, uploads, execution and assertions; this is not a nesting-only latency or a speed guarantee. These results extend the initial backend milestone; the physical-capture follow-up below records subsequent validation.

**Physical-capture follow-up:** 167 offline tests now pass after fixing unnecessary NFP decomposition and lead-in rejection on dense circle chords. The actual calibrated cardboard image returned one sheet and one L-shaped hole; natural-language orders, mixed nesting, verified output and a predicted inventory update were exercised in isolated test storage. The user physically remeasured and corrected the hole-offset references to 73/69 mm top/left; baseline extraction is 73.46/68.65 mm without adjustment. Exterior dimensions still differ by up to 4.7 mm from the ruler reference. See the [measured capture report](docs/architecture/PHYSICAL_VALIDATION_20261029.md); this is not overall physical accuracy acceptance.

Primary protocol references: [Meta segmentation](https://dev.meta.ai/docs/sam/segmenting), [mask grammar](https://dev.meta.ai/docs/sam/reading-segmentation), [official parser](https://dev.meta.ai/docs/sam/client-libraries), [GRBL supported modes](https://github.com/gnea/grbl/wiki), [GRBL laser mode](https://github.com/gnea/grbl/blob/master/doc/markdown/laser_mode.md).
