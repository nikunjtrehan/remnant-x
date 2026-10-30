# Backend capabilities and promise audit

Audit date: 29 October 2026; evidence updated 30 October 2026.
This milestone implements the photo-to-inventory,
order-to-nesting and verified-output backend. Physical acceptance and the explicit
architectural deviations below remain open. It is a software planning prototype;
it does not operate a machine.

The desktop and its required review/plan API contracts are now implemented.
Current evidence is in the [final integration review](../FINAL_READINESS.md).
Historical test runs below retain their original counts and timings.

The intended workflow combines SAM topology segmentation, calibrated CAD polygons,
material-aware multi-sheet inventory, natural-language or uploaded-DXF orders,
parallel NFP/annealing nesting and controller-specific verified output. This audit
maps those design claims to demonstrated behavior and limits. Private planning
transcripts and handoff notes are excluded from the public repository.

## Implementation audit

| Capability or original design claim | Current implementation and evidence | Status |
| --- | --- | --- |
| Real SAM 3.1 topology segmentation | Meta Responses integration and official decoding; two cardboard specimens, five usable views with correct topology and three blocked captures, followed by a real browser workflow. | Demonstrated within the measured cardboard scope; uniform physical accuracy acceptance pending. |
| Homography and millimetre CAD polygons | Four-marker, 16-corner planar calibration; polygon/DXF output. Contour approximation is called with zero simplification tolerance by default. | Implemented within stated station assumptions; physical accuracy unproven. |
| All internal holes preserved | Selected-mask interiors retained without cleanup; demonstrated an L opening and a second specimen with rectangular/circular holes and an exterior notch. | Two specimens tested; not a guarantee of every hole on arbitrary stock. |
| Spatial warehouse inventory | SQLite stores polygon geometry and material/thickness/provenance; local geometry supplies spatial operations. This is not an LLM-resident inventory graph. | Workflow implemented; architecture differs from the draft's framing. |
| Muse Spark 1.3 uses a 1M context to filter warehouse stock | Baseten Muse Spark Open is the default; direct Meta Muse Spark 1.3 parsing is configurable. Models interpret filter requirements; local SQL enforces exact identities and thickness. Warehouse contents are not sent as a 1M-token prompt. | Named model supported; the million-token warehouse-prompt architecture is deliberately not adopted. This is a deviation, not literal fulfilment of that sentence. |
| Exact grade, thickness, grain and kerf constraints | Exact material identities, thickness filtering, restricted rotations and placement clearances, with deterministic checks. | Implemented within the documented numerical tolerances. |
| 100+ incoming DXF parts | HTTP tests upload 101 distinct generated DXF definitions and execute one verified 101-part order; a separate two-definition, 105-instance batch uses multiple perforated sheets. | Both workloads pass. Files follow the documented straight-polyline contract; arbitrary industrial CAD is not claimed. |
| Parallel NFP and simulated annealing | One nester computes Minkowski-sum no-fit polygons using convex decomposition, contact placement and seeded, bounded parallel annealing chains. | Implemented. Independent membership/geometry tests and concurrency checks pass; no global-optimality or speedup guarantee. |
| Tight packing / maximum utilization | Valid placements, smaller-stock preference, hole reuse and multi-sheet backfill; measured utilization is reported. | Heuristic packing implemented; global optimality or a comparative yield improvement is not established. |
| Muse Code compiles coordinate trees | Real Muse Code prepared two Python emitter functions, with version/model/hash provenance. They format locally planned numeric blocks through a restricted contract and final verification. | Implemented on the preparation path, consistent with the hot/cold architecture; no coding-agent call per job. |
| Dialect-specific machine output | Bounded GRBL 1.1 laser and LinuxCNC spindle-style laser profiles. LinuxCNC establishes G61 and uses M2 rather than the baseline M30 end block. | Two documented profiles implemented; arbitrary/proprietary controllers remain unsupported. |
| G00/G01/G02 and pierce lead-ins | G00/G01 contours plus optional G02/G03 quarter-circle lead-ins. Explicit plane/IJ modes, analytic arc lengths, conservative sampled envelopes and waste clearance checks. | Implemented. Requested leads that cannot fit fail; lead cutting footprints are included in inventory updates. General helical/full-circle/arc fitting is outside this bounded profile. |
| Collision verification | Exact final text is parsed and checked against planned contours/leads, configured feed/power/dwell, supported commands and supplied stock before one batch commit. | Implemented for the documented command subset, numerical tolerance and geometry; no physical cutting certificate. |
| Guarantee of 0.00mm hole overlap | Software uses finite precision: default 0.01mm geometry buffer in toolpath verification, 0.0011mm coordinate comparison, and 0.001mm² placement overlap tolerance. Physical perception and cutting have additional uncertainty. | An absolute physical guarantee is unsupported; report numerical scope and tolerance. |
| CNC laser / waterjet execution and physical control | No machine connection, workholding qualification, kerf compensation, process qualification or cut-completion feedback. | Software planning prototype; physical manufacturing autonomy is not demonstrated. |

## Scope boundaries

Primary-first order routing remains the provisional choice after the recorded
120-trial comparison. Parallel agreement was slower and did not eliminate shared
interpretation mistakes. The current bounded correction cycle lets Fireworks
repair one rejected complete-order extraction, subject to the same requirements
checks. Missing information is never supplied by invention.

This is order-interpretation repair, not geometric repair or physical manufacturing
feedback. Optional surface advice remains advisory. Muse Code preparation is
implemented; Modal execution and real-time manufacturing guarantees are not.

## Corrections and acceptance evidence

Three regression tests reproduced concrete defects before correction:

1. An asymmetric part could lose a necessary rotation because equal rounded
   bounds, area and centroid were treated as evidence of symmetry. Rotation
   deduplication now compares actual polygon geometry.
2. The independent placement sanitizer checked containment but omitted outer-edge
   kerf clearance. It now checks that clearance with the existing 0.15mm allowance.
3. Duplicate visible station marker IDs silently overwrote earlier detections.
   Calibration now rejects duplicate station IDs before computing homography.

The fourth new test exercises managed HTTP uploads, exact SS304 stock selection,
105 mixed part instances, retained part holes, independent geometry/clearance
assertions, final G-code verification and unchanged inventory during preview.
That workload uses two synthetic DXF definitions: 70 plates with internal holes and 35 L-shaped parts, checking 175 contour loops. An additional test now uploads 101 distinct generated CAD definitions with varying dimensions, including holes and concave L-shapes, then executes one verified order. Neither is a live vision or physical cutting test.

Initial audit corrections passed 125 tests. After backend completion work, the full offline suite passed **164 tests, 0 failures, 0 skips** in **96.79 seconds** on this machine. In that suite, the 105-instance test took 11.80 seconds and the 101-file test took 60.07 seconds, including setup, uploads, execution and assertions. The physical-capture follow-up added three regression cases and two small geometry fixes; the latest full suite passed **167 tests, 0 failures, 0 skips** in **75.01 seconds**. A separate profiled 101-file run took 47.27 seconds. These are workload observations, not isolated nesting latency or performance guarantees. One Starlette/httpx
deprecation warning remains. Test source: [test_promise_acceptance.py](../../backend/tests/test_promise_acceptance.py).

The backend includes NFP/annealing, prepared Muse Code emitters, bounded arcs and explicit process inputs. The desktop follow-up adds reviewed photo intake and exact-plan recovery/confirmation; hardware feedback remains outside scope. Current local checks pass 184 backend tests and 42 frontend tests plus the production build. The regression suite makes no model calls. Separate live probes verified real Muse Code generation, Baseten parsing and Fireworks repair of an injected invalid fixture; see the [repository review](REPOSITORY_AUDIT.md).

## Work still required

- Extend the [two-piece physical experiment](PHYSICAL_VALIDATION_20261030.md)
  to more materials and capture conditions before general dimensional claims.
  Exterior error reached 7.32 mm; no real-machine process is qualified.
- The original algorithm and tool-generation commitments have backend implementations and tests. Retain the documented complexity/controller bounds and avoid describing heuristic search as a global optimum. The million-token warehouse prompt and broad physical safety guarantee remain explicit deviations; better wording cannot make those literal matches.
- Establish the intended meaning and bounded acceptance test for correction loops
  before describing them as autonomous or real-time manufacturing control.
- Retain the demonstrated [desktop workflow](../FINAL_READINESS.md) and its
  explicit review, stock identity and exact-plan boundaries.
