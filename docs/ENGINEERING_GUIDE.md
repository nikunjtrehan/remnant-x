# Engineering reference

Start with the [project README](../README.md) for the desktop workflow and setup.
This reference covers the API, geometry and controller contracts.

The direct API retains explicit legacy save/commit options for trusted callers.
The desktop instead uses pending optical reviews and stored verified plans;
see the [workflow guide](../Front%20End/WORKFLOW_GUIDE.md) for those contracts.

## Start the API without the PowerShell launcher

From the repository root, after dependency installation and provider setup:

```powershell
$env:REMNANTX_DB_PATH = 'demo_warehouse.db'
$env:REMNANTX_ARTIFACT_DIR = 'artifacts/demo'
.\.venv\Scripts\python.exe -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

This selects separate trial storage and does not seed inventory. The variables
apply to that terminal session; use a fresh shell when switching to another
warehouse. Both this API and the frontend must run for live work.

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

### Physical validation and remaining acceptance

Use your real printed station and measured cardboard. Keep the sheet flat and markers visible. Capture outer dimensions and every hole with a ruler or caliper, then index the same sheet at several positions and lighting conditions. Compare extracted widths, heights, hole count, hole dimensions and boundary overlays with the measurements. Repeat the exact frames with CLAHE on and off. Record the errors and set a suitable acceptance threshold for the machine and material before claiming physical accuracy. The two-specimen experiment includes real SAM geometry and measured errors, recorded in the [physical report](architecture/PHYSICAL_VALIDATION_20261030.md). Broader materials, capture conditions and machine tolerances remain unqualified.

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

Current regression and browser evidence: [frontend validation](../Front%20End/VALIDATION.md) and [final integration review](FINAL_READINESS.md). Physical measurements: [two-piece report](architecture/PHYSICAL_VALIDATION_20261030.md).

Primary protocol references: [Meta segmentation](https://dev.meta.ai/docs/sam/segmenting), [mask grammar](https://dev.meta.ai/docs/sam/reading-segmentation), [official parser](https://dev.meta.ai/docs/sam/client-libraries), [GRBL supported modes](https://github.com/gnea/grbl/wiki), [GRBL laser mode](https://github.com/gnea/grbl/blob/master/doc/markdown/laser_mode.md).
