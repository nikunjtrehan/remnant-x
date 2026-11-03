# Explain DXF fit separately from import success

A readable drawing may still be too large for the selected stock. Previously,
an area filter hid undersized compatible remnants, and the UI listed opaque
unplaced IDs without an explanation. If every sheet was undersized, the API
could misleadingly report that no compatible material existed.

The planner now retains all material/thickness-compatible, selected stock in
smallest-first order. An area check skips impossible searches cheaply. The
result's `nesting.placement_checks` records, for each needed part and remnant,
the requested, placed and remaining quantities, drawing bounds, reason and next
step. Later unused sheets are not described as failed attempts.

Reasons distinguish a drawing matching the entire remnant, insufficient material
area, an excessive span, insufficient remaining area and disconnected free
regions. These are geometric constraints. Other unsuccessful searches say
**no position found**; a bounded search does not prove global infeasibility.
The report does not rerun the solver or infer the missing fit reason with AI.

The UI distinguishes complete, partial and zero-placement results; it displays
per-remnant explanations and lets the worker inspect a sheet even when zero
parts were placed. Incomplete previews do not become completed inventory cuts.

Eight offline backend regressions cover these constraints, successful spillover,
partial quantities, unchanged inventory, zero-clearance semantics and a part
that can fit diagonally despite exceeding the sheet's width. Frontend tests
cover the visible explanations, stock selection and unavailable cut actions.

The [sample mounting plate](../../examples/mounting_plate_60x40mm.dxf) provides
a separate part drawing for rehearsal. Live fit checks against copies of the
two recorded metal geometries placed all three requested plates on Metal-A.
Those previews did not change the recording inventory or qualify a cutting machine.
