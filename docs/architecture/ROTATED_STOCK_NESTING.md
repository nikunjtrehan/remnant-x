# ADR 011 Sheet aligned placement rotations

Status: implemented and checked against the three-copy physical-photo job.

## Problem

The workbench accepted a vendor part at approximately 168.9 by 167.7 mm with five internal holes. A three-copy job used two cardboard remnants. The original search placed one part on Piece B and one on Piece A, leaving one unplaced.

The L-shaped remnant was rotated about 13.48 degrees in the station image. The nester searched only station-aligned 0/90/180/270 degree part orientations. Its greedy result did not establish that another physical placement was impossible.

## Choice

For parts without a grain lock, retain the four station-aligned orientations and also test four orientations aligned with the stock polygon's minimum rotated rectangle. Near-axis offsets below 0.1 degree are treated as the existing station frame. Cache the angle set per sheet.

Grain-locked parts retain the existing station-aligned 0/180 policy. Do not silently rotate them into a new material frame.

Use the same unchanged stock and part polygons for placement checks. Reject candidates with insufficient separation before computing intersection area; this avoids unnecessary overlay operations for colliding candidates.

The existing bounded grid fallback remains available when an NFP complexity budget is exceeded. Neither an angle list nor a sampled grid proves a global optimum.

## Verification

The actual accepted photo geometries and the original-size vendor part placed all three requested copies: one on Piece B and two on Piece A. Both compiled programs passed verification. The checks reported zero path length across stock holes and zero path length outside the sheets. The programs contained six and twelve contour loops respectively. Inventory was not modified by this validation.

A generated rotated-sheet regression independently exercises two parts, an L-shaped internal hole, grain-lock restrictions, placement sanitization and final G-code verification. The vendor artwork and private station photographs are not distributed as test fixtures.

## Consequences

Image orientation no longer limits free parts to the station axes. Additional orientations increase search work. The observed real three-copy run took about 46 seconds in a local in-memory check; this is an observation, not a latency guarantee. Worker review and physical process qualification remain necessary.
