# Sample part drawing

`mounting_plate_60x40mm.dxf` is a generated 60 × 40 mm rectangular plate
with two 6 mm bolt holes, centred at (12, 20) and (48, 20) mm. The holes
use closed 64-segment polylines, within the supported DXF geometry.

Upload it under **Vendor parts**, choose the stock's actual material and
thickness, and request **“Cut 3 copies of this.”** Review its dimensions
before nesting. This is a new part drawing; station photos and their exported
DXFs describe the remnant stock.

The application checks compatible remnants from smallest to largest. It
reports how many copies were placed on each and why others were not placed.
A failed search is distinguished from an area or size constraint that proves
the part cannot fit. It never scales a drawing to force it into stock.

This example defines geometry, not qualified machine process settings.
