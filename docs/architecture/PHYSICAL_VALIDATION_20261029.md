# First cardboard capture: raw and calibrated tests

29 October 2026. This is an incomplete physical validation, not an accuracy pass.
Initial raw-image diagnostics were followed by actual calibrated endpoint tests
after the station inputs were confirmed. Findings led to two small geometry fixes
described below. Real inventory and configuration were not changed.

## Independent reference supplied by the user

| Item | Measurement |
| --- | --- |
| Black chart paper | 682 × 525 mm |
| Cardboard exterior | 319 × 289 mm |
| Cardboard thickness | 3 mm |
| Enclosed L-shaped hole overall extent | 158 × 156 mm |
| Vertical arm width / horizontal arm height | 25 / 53 mm |
| Inner vertical / horizontal lengths | 103 / 133 mm |
| Hole left offset | 69 mm, corrected by the user's physical remeasurement |
| Hole top offset | 73 mm, corrected by the user's physical remeasurement |
| Marker square | User confirmed 48 mm, complete black square including black border |

The arm measurements close consistently: 25 + 133 = 158 mm and
103 + 53 = 156 mm. The idealized reference areas are exterior 92,191 mm²,
hole 10,949 mm² and usable material 81,242 mm². These are reference calculations,
not image-derived measurements. Measuring-instrument resolution and acceptance
tolerances have not been supplied. None of the specimen dimensions was sent to SAM
or used to calibrate the image.

Reference revision: the original handwritten offsets were 60 mm left and 93 mm
top; the top value was initially reconfirmed. After reviewing the discrepancy,
the user physically remeasured the same specimen and corrected them to 69 mm left
and 73 mm top. The original notes and comparisons are retained privately. This
follow-up was made after seeing the estimates, not as a blind repeat. The image,
station calibration, SAM masks and extracted geometry were not rerun or adjusted
to obtain agreement. Other reference dimensions remain unchanged.

## Station diagnostic

The 1280 × 997 pixel photograph detects DICT_4X4_50 IDs 0, 1, 2 and 3 at
top-left, top-right, bottom-right and bottom-left respectively.
Photo SHA-256: `360952bd851d39c11c8211bf86f73082e851418c9a331b556c7744e1135492b6`.

The backend defines station width/height at the outer black marker edges, rather
than at the paper boundary. Testing paper dimensions as station dimensions with a
48 mm marker produced `ERR_CALIBRATION_DRIFT`: measured marker 50.43 mm versus
expected 48 mm. This rejected configuration was not used to report metric errors.
Top, bottom, left and right black-marker spans were then supplied: 657, 658, 509
and 514 mm respectively.

## Live SAM diagnostics on the original image

These are original-image tests, not the production rectification → corner masking
→ SAM sequence. Box bounds came from looking at the photo, without using the
specimen measurements. The supported box prompt was [350, 140, 1080, 835] pixels,
right/bottom exclusive. Surface auditing was disabled; no other provider was called.

| Input | Observed result | Elapsed time |
| --- | --- | --- |
| Concept `cardboard sheet` | Did not yield exactly one selectable mask; rejected | 10.67 s total |
| Box, CLAHE off | One SAM mask object; 7 foreground components and 11 holes | 7.00 s transport / 7.20 s total |
| Same box, CLAHE on | One SAM mask object; 2 foreground components and 7 holes | 6.49 s transport / 6.60 s total |

Both box results preserve the large L-shaped opening, but also contain extra
foreground islands and apparent holes. Visual review confirms spurious topology;
one selected SAM object is not necessarily one clean physical polygon.
The existing vectorizer rejected both masks with `ERR_MULTIPLE_SHEETS` when tested
at its default 2 px/mm resolution. This check did not establish a valid metric scale.
No disconnected islands or small holes were silently removed to obtain a pass.

There was one observation per setting. These results do not establish repeatability,
physical dimensional errors or that CLAHE should become the default. They do not
establish how the correctly configured, rectified production input will perform.

## Calibrated endpoint test after confirmation

The existing API accepts rectangular station width and height. The recorded
approximation uses arithmetic means of opposite spans: 657.5 × 511.5 mm, marker
48 mm, resolution 2 px/mm. This does not model the four unequal spans exactly.
The top/bottom mismatch is 1 mm and left/right mismatch is 5 mm. No scale was
adjusted to match the cardboard measurements.

The current internal calibration check accepts this configuration: mean marker
size 48.76 mm, mean size drift 0.76 mm, 16-corner RMS residual 1.05 mm and maximum
corner residual 1.42 mm. Individual transformed marker sides range from 47.36 to
50.00 mm. These use the fitted references and do not establish independent accuracy.

Actual `POST /api/v1/index-remnant` requests used the original photo, cardboard/3 mm,
these station inputs, SAM concept `cardboard sheet`, surface audit off and warehouse
saving disabled. Both requests followed calibration → corner masking → real SAM →
unmodified vectorization → DXF export. Neither used a box or cleanup/filtering.
Both returned HTTP 200 / `INDEXED_OK`, one sheet and one enclosed L-shaped hole.
The no-CLAHE request took 7.29 seconds overall; CLAHE took 9.76 seconds. One run per
setting does not establish latency or segmentation repeatability. Rectification,
corner masking, resolution and model variability were not isolated individually;
these results do not prove which change caused the improvement over raw diagnostics.

## Independent metric comparison

Exterior dimensions use its minimum-area bounding rectangle. Hole dimensions and
offsets use those detected axes. Arm widths use cross-sections at 75% of observed
hole height/width. This analysis does not fit the result to reference dimensions
and does not replace the original extracted polygon. Irregular hand-cut edges and
the meaning of the ruler measurements can affect comparison with rectangle extents.

| Feature | User reference | SAM, CLAHE off | SAM, CLAHE on |
| --- | ---: | ---: | ---: |
| Outer width, mm | 319 | 323.7 | 323.7 |
| Outer height, mm | 289 | 292.0 | 292.1 |
| Hole width, mm | 158 | 161.6 | 161.6 |
| Hole height, mm | 156 | 159.9 | 160.2 |
| Vertical arm width, mm | 25 | 27.0 | 26.7 |
| Horizontal arm height, mm | 53 | 53.5 | 53.5 |
| Hole left offset, mm | 69 | 68.6 | 68.5 |
| Hole top offset, mm | 73 | 73.5 | 73.4 |
| Exterior area, mm² | 92,191 | 92,726.1 | 92,759.0 |
| Hole area, mm² | 10,949 | 11,276.6 | 11,289.0 |
| Usable area, mm² | 81,242 | 81,449.5 | 81,470.0 |

Decimal formatting is arithmetic reporting, not a claim of submillimetre accuracy.
For the baseline, exterior width/height errors are +4.7/+3.0 mm, and hole extent
errors +3.6/+3.9 mm. Against the corrected references, the unrounded baseline top
offset is 73.4626 mm (error +0.4626 mm) and left offset 68.6481 mm (error -0.3519 mm).
For CLAHE, the corresponding errors are +0.3681 mm and -0.5425 mm. These agree
closely with the reported whole-millimetre remeasurement; they do not establish
general submillimetre accuracy or resolve the remaining size errors.
A small net usable-area difference (+0.26%) combines
exterior and hole errors and does not establish accurate boundaries.

Both calibrated settings have the correct topology. This single paired frame does
not justify making CLAHE the default; it remains off. Repeat captures, explicit
measurement definitions, instrument resolution and acceptance tolerances are still
needed. No physical accuracy or real-machine qualification is claimed.

## Downstream findings

The uncorrected baseline SAM polygon was copied into a separate experimental SQLite
warehouse as cardboard, with real SAM provenance. The natural-language five-disc
order parsed through Baseten and produced verified output. The mixed-order test
then found unnecessary NFP decomposition work on dense concave photo contours plus
a ring: it reached the 20,000-pair budget. The fix extends the existing hole-area
containment bound to concave shells. It preserves concavity, contour detail and
search limits; independent intersection tests cover both operand orders.

After that fix, the requested 2 mm ring lead-in hit an overly restrictive chord
length guard. The planner now allows short chords and uses its existing independent
arc envelope/solid/stock checks to decide whether the approach fits. Circle and
ring-hole regression tests cover this case. A requested unsafe approach still fails.

The final mixed test placed two 30 × 20 mm rectangles, two 20 mm discs and one
40/20 mm ring. LinuxCNC output with 2 mm lead-ins passed final verification and
independent containment/overlap/hole checks. It took 26.04 seconds while the full
suite ran concurrently; this is not an isolated latency benchmark. An oversized
400 × 400 mm part was rejected during stock selection without changing test stock.

An additional actual indexing request repeated the baseline input and saved only
to the isolated experimental database. It again returned one piece and one hole,
in 21.01 seconds overall. The two baseline masks differ by 10 pixels, with
intersection-over-union 99.9969%. This checks repeatability on the same digital
input, not across new captures, positions or lighting conditions.

The repeated index result then completed a five-disc predicted-cut commit in that
isolated database, using the previously validated Baseten order without another
model request. All programs verified; usable stock changed from 81,448.5 to
79,717.3 mm², the stale DXF reference was cleared and SAM provenance was retained.
No physical machine was run, and the user's real warehouse was unchanged.

After both fixes, the full offline suite passed **167 tests, 0 failures, 0 skips**
in **75.01 seconds**, with one existing Starlette/httpx deprecation warning.

Originals, masks, overlays, response text and run metadata are retained privately
under the ignored `.task-tmp/physical-validation/20261029-l-cutout/` directory.
Protected configuration/database hashes were unchanged for every live call.
