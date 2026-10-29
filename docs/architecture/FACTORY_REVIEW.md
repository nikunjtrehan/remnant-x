# Desktop geometry review and recovery

Status: Implemented · 30 October 2026

## Decisions

1. **Separate analysis from stock eligibility.** A model can produce a valid
   polygon that misses the physical outline or a hole. Desktop scans therefore
   create a durable pending review. The worker compares geometry against the
   calibrated photograph and accepts it before it enters usable inventory.
   This is visual inspection, not manual measurement of every feature.
2. **Confirm the exact reviewed plan.** Replanning at the stock-update step can
   produce a layout the worker never reviewed. Complete verified plans now retain
   their programs, footprints and original stock snapshots. Confirmation uses
   those saved footprints, rejects stale stock and writes a replay receipt in
   the same SQLite transaction. Operator-reported completion is kept distinct
   from program download and machine telemetry.
3. **Recover work within the existing stack.** Original photo files and queue
   metadata use browser IndexedDB; lightweight job/view state uses local storage.
   Completed reviews and plans use two tables in the existing SQLite database.
   Stable IDs recover completed results without repeating inference or nesting.
   No distributed queue, additional backend service or agent framework is added.
4. **Connect logical stock to physical stock.** The worker supplies a physical
   stock ID and rack/slot. Labels and the cutting-plan sheet identity use that
   record. An exact image duplicate is detectable; different views of the same
   physical sheet still require the same physical identity and operator discipline.

## Tradeoffs and boundaries

Visual acceptance adds an operator step. Glare, hidden edges and flatness are not
automatically certified. Browser recovery requires the same origin and available
storage; an interrupted backend computation is not a resumable background job.
Current-stock checks and atomic stale rejection do not provide factory-wide
physical sheet reservations. Remaining geometry is predicted from the verified
program rather than measured after cutting.

Legacy direct API auto-save/commit contracts remain available to trusted callers;
the desktop uses explicit optical review and saved-plan confirmation.

## Evidence

41 frontend tests and 184 offline backend tests pass. The isolated browser
exercise verified missing-marker rejection, two analyses held outside inventory,
reload recovery without additional perception calls, physical labels, a 50-copy
DXF plan, exact-plan completion and blocked stale export.

See the [factory scenario matrix](../../Front%20End/FACTORY_SCENARIOS.md) and
[validation record](../../Front%20End/VALIDATION.md). These workflow tests used
explicit offline perception and do not establish new live SAM accuracy.
