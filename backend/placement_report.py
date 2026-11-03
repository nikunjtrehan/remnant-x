"""Explain a nesting result without claiming a failed search proves no fit."""
import math
from collections import Counter

from backend.db_and_parts import CADPartFactory


def _failure_reason(part, sheet, free_space, kerf_mm):
    poly = part.polygon
    if kerf_mm > 0 and CADPartFactory.normalize_to_origin(poly).equals(
        CADPartFactory.normalize_to_origin(sheet.polygon)
    ):
        return (
            "STOCK_OUTLINE",
            f"The drawing matches this entire remnant, including its holes. "
            f"It leaves no room for the {kerf_mm:g} mm kerf clearance.",
            "Upload the drawing of the intended part, or choose larger stock.",
        )
    if poly.area > sheet.polygon.area + 1e-6:
        return (
            "INSUFFICIENT_AREA",
            f"One part needs {poly.area / 100:.1f} cm² of material; this remnant "
            f"has only {sheet.polygon.area / 100:.1f} cm² after excluding existing holes.",
            "Choose a larger remnant, or check the drawing's size and units.",
        )
    px, py, qx, qy = poly.bounds
    sx, sy, tx, ty = sheet.polygon.bounds
    # Width > sheet width alone is not proof when rotation is allowed.
    if max(qx - px, qy - py) > math.hypot(tx - sx, ty - sy) + 1e-6:
        return (
            "EXCEEDS_REMNANT_SPAN",
            "The part is longer than this remnant can span, even when rotated.",
            "Choose longer stock, or check the drawing's dimensions and units.",
        )
    if poly.area > free_space.area + 1e-6:
        return (
            "INSUFFICIENT_FREE_AREA",
            f"One copy needs {poly.area / 100:.1f} cm²; only "
            f"{free_space.area / 100:.1f} cm² remains after clearance and any placed parts.",
            "Use additional stock for the remaining copies, or reduce the order quantity.",
        )
    if free_space.geom_type == "MultiPolygon" and all(
        region.area + 1e-6 < poly.area for region in free_space.geoms
    ):
        return (
            "FRAGMENTED_FREE_SPACE",
            "Enough total area remains, but it is split into regions that are each "
            "too small for one connected part.",
            "Choose stock with a larger continuous region around its existing holes.",
        )
    return (
        "NO_POSITION_FOUND",
        "No valid position was found with the searched rotations, existing holes, "
        "clearance and other planned parts. Another layout may fit.",
        "Try different or larger stock; check the part dimensions and rotation restrictions.",
    )


def build_placement_checks(sheets, part_specs, result, kerf_mm):
    """Per-part counts and reasons in the actual smallest-first sheet order.

    Reconstruct the final plan's free space, not speculative alternative runs.
    Satisfied parts are not reported as failed on later, unneeded sheets.
    """
    remaining = {p.part_id: p.quantity for p in part_specs}
    outcomes = {o.sheet_id: o for o in result.sheet_outcomes}
    checks = []
    half_kerf = kerf_mm / 2
    for sheet in sheets:
        outcome = outcomes.get(sheet.sheet_id)
        placed = outcome.placed_parts if outcome else []
        counts = Counter(p.part_id for p in placed)
        free = sheet.polygon.buffer(-half_kerf, quad_segs=16) if half_kerf else sheet.polygon
        for instance in placed:
            footprint = instance.polygon.buffer(half_kerf, quad_segs=16) if half_kerf else instance.polygon
            free = free.difference(footprint)
        for part in part_specs:
            before = remaining[part.part_id]
            if not before:
                continue
            count = counts[part.part_id]
            after = before - count
            code, message, next_step = (
                _failure_reason(part, sheet, free, kerf_mm) if after else
                ("PLACED", "All copies still needed were placed on this remnant.", "")
            )
            x0, y0, x1, y1 = part.polygon.bounds
            checks.append({
                "sheet_id": sheet.sheet_id, "part_id": part.part_id,
                "width_mm": round(x1 - x0, 2), "height_mm": round(y1 - y0, 2),
                "requested": before, "placed": count, "remaining": after,
                "reason": code, "message": message, "next_step": next_step,
            })
            remaining[part.part_id] = after
    return checks
