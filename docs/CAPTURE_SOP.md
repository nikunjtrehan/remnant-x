# Capture and review SOP

This procedure describes the local photo-to-inventory workflow. It is not a
laser-operation procedure. Use [local startup](LOCAL_STARTUP.md) for installation.

## Recorded setup and evidence

The measured station uses `DICT_4X4_50` ArUco IDs **0 top-left, 1 top-right,
2 bottom-right and 3 bottom-left**. The recorded spans are **657/658 mm**
top/bottom and **509/514 mm** left/right; black marker cores are **48 mm** wide,
excluding the white border. The rectangular approximation is **657.5 × 511.5 mm**.
These measurements belong to this station. Measure another station independently.

| Capture detail | What the available experiment record establishes |
| --- | --- |
| Camera model, resolution and lens setting | Not recorded. No camera model or lens calibration is claimed. |
| Lighting type, position and glare control | Not recorded as a controlled setup. Broader glare conditions have not yet been characterized. |
| Camera height, distance and angle | Exact values not recorded. The cardboard report distinguishes near-overhead, rotated and oblique views; it does not establish an accepted angle range. |
| Marker fixing method | Not recorded. The method cannot be inferred from successful marker detection. |

Record those four details during a repeat experiment; do not treat an unspecified
value as a requirement or a verified configuration. The existing evidence is
[two metal photos with the expected 2 and 5 holes](architecture/SAM_PROMPT_RECOVERY.md)
and a separate [measured cardboard experiment](architecture/PHYSICAL_VALIDATION_20261030.md).
The metal hole counts do not establish dimensional accuracy.

## 1. Prepare and photograph each distinct remnant

1. Keep the measured markers fixed on one flat surface, with their black cores
   and white quiet-zone borders unobstructed. Replace damaged markers and
   remeasure if their positions change.
2. Place one flat remnant entirely inside the station. Use a matte, contrasting
   background; remove hands and clamps from its outline and holes. Adjust the
   lighting or recapture when glare obscures a boundary. This is capture guidance,
   not a claim that any particular lighting arrangement was tested.
3. Give the physical remnant one stock ID. Take one complete station photo per
   distinct sheet. Multiple views of the same sheet are not additional inventory.
4. Supply the actual material grade and thickness. SAM does not determine either.
   Preserve these identifiers and the physical sheet orientation for later handling.

## 2. Import, check and review

1. Choose **Scan a remnant → Batch photos / ZIP**, name the batch and upload the
   photos. The importer enforces 50 JPEG/PNG images, 20 MB each and 100 MB total.
2. Set the material and thickness; apply them to unprocessed photos. Review each
   thumbnail. Rejected files and duplicates need attention rather than renaming.
3. Run **Check markers in photos**. Marker/calibration failures stop before SAM.
   Recapture if a marker is missing or obscured; verify measured station settings
   if the calibration still fails.
4. Run **Find outlines & holes**. Generic `sheet` requests use the supplied material
   to choose a more specific concept, such as `metal sheet`. An explicit concept
   remains explicit. This is prompt targeting, not automatic material recognition.
5. Compare the extracted exterior and **every existing hole** with the photograph.
   Missing or invented geometry must not be accepted. For a failed detection,
   correct **What should SAM find?**, review the available guidance or recapture.
   Recovery is bounded; box/crop alternatives are not automatic proof of correctness.
6. Accept each reviewed geometry explicitly. Only accepted sheets become available
   stock. Recover saved reviews after interruption instead of indexing another
   stock record for the same piece.

## 3. Check dimensions and clearance before planning

For a new capture setup, independently measure specimen dimensions and hole
locations before examining model results. Keep those measurements as validation
references, separate from perception inputs. Establish an acceptance tolerance
appropriate to the actual cutting process with its operator.

The cardboard experiment's exterior-dimension median absolute error is about
**4.15 mm**, with **7.32 mm worst case**. Across all 50 published dimension/span/
offset comparisons, median absolute error is about **1.45 mm**. These are a small,
non-blind experiment's results, not a metal tolerance or a safe clearance setting.

The order's **`kerf_mm` is the requested planning gap** between parts and from
stock boundaries/holes; the UI default is **1 mm**, and the accepted range is
0–15 mm. Stock-consumption accounting buffers cut geometry by half that value.
The program follows centerline contours without dimensional kerf compensation.
There is **no additional calibrated photo-error allowance**. Do not treat 0.2 mm,
1 mm, or any other selected gap as evidence that the measured capture errors are
covered. The software verifier checks accepted geometry, not the physical sheet.

## 4. Review the job and hand it over

1. Select the intended batch or compatible inventory. Review prompt dimensions,
   units, material, thickness and quantities; for a DXF, inspect its imported
   millimetre size and hole count. Files are not silently scaled to fit stock.
2. Inspect the plan for every used sheet and read partial/unplaced-part reasons.
   A partial plan cannot update inventory. Failed verification blocks export.
3. Download the selected-profile programs only after reviewing the result.
   Remnant X emits software-verified G-code for GRBL and LinuxCNC profiles.
   Actual controller execution and controller-simulator execution have not been
   demonstrated. The on-screen path playback is a visualization.
4. The machine operator must establish controller compatibility, material/process
   settings, fixturing, work origin and sheet orientation. Moving a sheet from
   the capture station does not transfer its coordinate registration automatically.
5. Report completion only after the exact reviewed job was physically cut.
   Downloading or previewing a plan does not consume inventory. The completion
   transaction applies all affected sheets together and rejects stale stock.
