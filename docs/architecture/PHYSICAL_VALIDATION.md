# Independent physical ground truth for photo indexing

Decision date: 29 October 2026.

Status: First photo and specimen measurements received on 29 October 2026.
Initial image-space SAM diagnostics are recorded in the [first-capture report](PHYSICAL_VALIDATION_20261029.md).
Marker spans and square size were subsequently confirmed. The actual calibrated
endpoint accepts the image with one sheet and one L-shaped hole. Physical
remeasurement corrected the original hole-offset notes; the corrected offsets
agree closely with extraction. Exterior and hole size errors remain, and no
overall physical accuracy acceptance has been established.

## Decision

Validate the photographed remnant against separately measured physical geometry.
The first planned specimen is rectangular cardboard containing an L-shaped cutout.
Record whether that cutout is an enclosed hole or an edge-connected notch.

Station calibration and remnant ground truth serve different purposes:

- During station setup, measured marker sizes and arrangement establish the reference geometry used to convert image coordinates to millimetres.
- During normal indexing, the worker supplies a photo, material identity and sheet thickness. The system should extract the existing outer boundary and holes without the worker entering their dimensions or positions.
- During this experiment only, ruler or caliper measurements of the cardboard and cutout provide an independent reference. These measurements must not be supplied to SAM or geometry extraction to construct or correct the result under evaluation.
- Dimensions of new parts requested for cutting still come from the order or uploaded DXF; they are separate from existing remnant geometry.

## Why

Successful geometry checks against a supplied mask establish consistency with that
mask. They do not establish that the mask matches the physical sheet. ArUco marker
residuals are also internal calibration checks, not independent evidence of remnant
measurement accuracy. Requiring production workers to measure every existing hole
would undermine the purpose of photo indexing.

## Evidence to collect

Preserve the original photo, measured station configuration, physical specimen
measurements, measuring instrument and its resolution, and the processing settings.
Record that this specimen is cardboard rather than presenting it as metal stock.
Keep experimental inventory separate from real warehouse records.

Run actual SAM segmentation, retain its output and the inferred metric geometry,
and compare outer dimensions, cutout dimensions and position, usable area and hole
topology against the independent reference. Report numerical errors and failures,
with the limitations of the reference measurements. Repeat captures at different
positions and angles before claiming repeatability. Agree acceptance tolerances
before judging the results; none have been established yet.

Nesting and final G-code verification can then be tested against the extracted
geometry. Passing those checks does not qualify a physical cutting process or
establish machine registration, kerf compensation or material-specific settings.

## Outcome

The initial raw-image diagnostic detected all four markers, but paper dimensions
failed when used as marker spans. Raw SAM masks contained spurious topology.
After station confirmation, the real calibrated endpoint returned one sheet with
one L-shaped hole, both with and without CLAHE, without mask cleanup. The baseline
exterior is about 323.7 × 292.0 mm versus the reference 319 × 289 mm. The user
remeasured the hole offsets as 73 mm top and 69 mm left, correcting the original
93/60 mm notes; baseline extraction is 73.46/68.65 mm. Extraction was not adjusted.
Downstream tests use a separate experimental
warehouse; real inventory is unchanged. See the first-capture report for settings,
measuring methods, failures and follow-up fixes. Repeats and acceptance tolerances
are still required before declaring physical accuracy.
