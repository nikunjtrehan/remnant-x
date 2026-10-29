# Desktop workflows and design decisions

## Current workflow contract

| Workflow | Support |
| --- | --- |
| Multiple vendor DXFs and quantities | Yes; 101 distinct definitions and a separate 50-copy order were previously exercised in the browser |
| One uploaded DXF plus a natural-language quantity | Yes; upload is attached to parsing, then the structured order is reviewed before nesting |
| Multiple remnant photos | Yes; independent checks, settings, results and warehouse saves in one intake queue |
| ZIP of remnant photos | Yes; JPEG/PNG files, including folders inside the archive |
| Many sheets in a manufacturing order | Yes; existing backend nesting and verification remain authoritative |
| Review before stock eligibility | Yes; the desktop stores a pending analysis, overlays geometry on its photograph, and requires explicit acceptance |
| Physical sheet IDs and rack/slot | Yes; stored location, printable stock labels, and sheet identity on the plan |
| Refresh recovery | Yes; browser photo files/drafts plus durable backend reviews and verified plans |
| Many disconnected sheets inside one photograph | Not supported by this indexing contract; use one photograph per distinct remnant |

For example: “Make 50 copies of the uploaded DXF from 3 mm ss304 sheet, kerf 1 mm.”
Material grade and thickness must describe the available stock; the DXF supplies
the part geometry. Multiple DXFs can use explicit quantities in the parts list;
the deterministic offline parser deliberately requires that route for multiple
uploads. Missing job inputs still require clarification.

Every stock photograph must include the station's four markers. The queue uses
the same saved station configuration as single-photo capture. Per-photo material,
thickness, concept and optional rectified-image box are editable before analysis.
A station change invalidates unchecked-photo calibration and region boxes.
Completed reviews retain their immutable image, geometry and calibration frame.

## Research applied

- **Artifact-first workspace**, informed by OrgLens, Elisa and Wrench Board:
  retain the large millimetre viewer, expose the actual placement count and sheet
  summary immediately, and make importing stock a prominent entry action.
- **Guided setup**, informed by Gaze Link: one shared station profile, per-photo
  marker checks and a visible queue of problems. A bad photo does not erase the
  other photos or become an accepted sheet.
- **Explicit job states and review**, informed by CrossBeam and Medkit: distinguish
  ready, blocked, analyzing, added and unconfirmed outcomes. Validate material and
  thickness before sending ready photos to SAM; inspect current inventory IDs to
  avoid accidentally replacing a record.
- **Curated result and recorded walkthrough**, informed by CrossBeam/Wrench Board:
  retained, with example/live separation. No replacement output or invented live
  progress is introduced.
- **Readable operational text**: larger fields/instructions and darker secondary
  text. The contrast target for ordinary text follows [W3C's minimum-contrast
  guidance](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html).
  This is not a claim of full accessibility certification.

These reference projects informed the interaction choices. Their results do not
establish which individual feature caused a win.

## Batch semantics and limits

- Up to 50 photos, 20 MB each, 100 MB total queued images. ZIP input is limited to
  100 MB; image counts/declared expansion sizes are checked before decoding.
- ZIP contents are read in the browser using the documented
  [fflate ZIP API](https://github.com/101arrowz/fflate). No server unzip service or
  extracted filesystem tree is added. Bad archives produce an import error.
- Exact duplicate image bytes are skipped using SHA-256. This does not recognize
  different photographs of the same physical sheet; the operator must submit one
  photo per distinct inventory item.
- Checks and segmentation run sequentially through the existing endpoints. Batch
  means a queue of many independent sheets, not parallel cloud inference.
- Each successful analysis becomes a pending review, outside usable inventory.
  The operator accepts or rejects individual geometry; accepted sheets save
  independently. Bad photos remain visible and completed analyses are not repeated.
- “Stop after current photo” stops before the next request. It does not claim to
  cancel an already running server/model call.
- Original files and lightweight queue metadata are checkpointed in IndexedDB;
  job drafts and view preferences use local storage. Large review images are
  loaded from the backend rather than duplicated in every browser checkpoint.
- Durable reviews and verified plans use two tables in the existing SQLite DB.
  Stable request IDs prevent completed work being repeated during recovery.
  Geometry acceptance and exact-plan confirmation are replay-safe transactions.
- A refresh restores saved work without automatically starting inference.
  Browser quota/storage failures show a warning. Browser data clearing, another
  browser origin and a backend computation interrupted before a result was
  stored are outside automatic recovery.

## Exact reviewed plans

The desktop supplies a plan ID to `/execute-pipeline`. Complete verified output,
original stock snapshots and cut footprints are saved together. Program download
checks the current stock; stale output is labelled outdated and blocked.
`POST /verified-plans/{plan_id}/confirm` requires `operator_confirmed=true`.
It applies the saved footprints and stores its receipt in the same transaction.
Retries return that receipt; they do not renest or subtract stock twice.
Completion is operator-reported and remaining stock is a geometric prediction.

The older direct API contracts remain available: `save_to_warehouse=true` indexes
without the desktop review step; `commit_cuts_to_db=true` executes and commits a
newly generated batch. The desktop uses neither shortcut. Reviewed scans send
`save_to_warehouse=false` and `review_id`; reviewed plans use the separate
confirmation endpoint. This preserves existing automation clients while giving
the desktop explicit human review.

## Validation boundaries

Frontend tests cover ZIP/loose files, nested images, import limits, malformed
archives, duplicate bytes, per-photo marker rejection, metadata requirements,
partial success, repeat prevention, shared station configuration, stop-after-current
and duplicate inventory IDs. Station edits invalidate pending checks while keeping
the setup panel open. The DXF prompt test checks that the uploaded path and
requested quantity stay bound.

The browser ZIP test used three synthetic photos with real marker/calibration
checks and an explicitly stubbed perception function: two accepted and saved,
one blocked for a missing marker. The uploaded-DXF prompt was exercised with the
real deterministic fallback, nesting and final verification. No paid inference or
production inventory was used. These tests establish workflow behavior, not
new SAM accuracy or live multi-photo cloud throughput.

See [FACTORY_SCENARIOS.md](FACTORY_SCENARIOS.md) for operating scenarios and
the distinction between automated checks and required visual inspection.
