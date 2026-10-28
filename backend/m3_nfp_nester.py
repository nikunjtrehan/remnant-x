from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Set, Tuple, Union
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.prepared import prep

from backend.db_and_parts import CADPartFactory, CADPartSpec, RemnantRecord


@dataclass
class PlacedPartInstance:
    instance_id: str
    part_id: str
    name: str
    sheet_id: str
    x_mm: float
    y_mm: float
    rotation_deg: float
    polygon: Polygon


@dataclass
class SheetNestingOutcome:
    sheet_id: str
    outer_area_mm2: float
    initial_usable_area_mm2: float
    remaining_usable_area_mm2: float
    utilization_pct: float
    placed_parts: List[PlacedPartInstance] = field(default_factory=list)
    kerf_safe_zone_polygon: Optional[Polygon] = None


@dataclass
class BatchNestingResult:
    status: str
    total_requested: int
    total_placed: int
    sheets_used: int
    sheet_outcomes: List[SheetNestingOutcome]
    unplaced_instances: List[str]
    sanitizer_verified: bool


class HoleAwareNester:
    """Module 3: Deterministic 2D Hole-Aware Nesting Engine & Server-Side Sanitizer.

    Uses Shapely 2.x C++ GEOS spatial indexing (prepared.prep) to pack parts around
    interior SAM 3.1 cutout holes and inside hollow donut-part centers.
    """

    def __init__(
        self,
        kerf_mm: float = 3.0,
        coarse_step_mm: float = 8.0,
        fine_step_mm: float = 1.0,
    ):
        self.kerf_mm = float(kerf_mm)
        self.coarse_step_mm = float(coarse_step_mm)
        self.fine_step_mm = float(fine_step_mm)
        if not all(math.isfinite(v) for v in (self.kerf_mm, self.coarse_step_mm, self.fine_step_mm)) or self.kerf_mm < 0 or min(self.coarse_step_mm, self.fine_step_mm) <= 0:
            raise ValueError("ERR_INVALID_NESTING_STEPS_OR_KERF")

    @staticmethod
    def _rotate_and_normalize(poly: Polygon, angle_deg: float) -> Polygon:
        if angle_deg % 360.0 == 0.0:
            return CADPartFactory.normalize_to_origin(poly)
        rotated = affinity.rotate(poly, angle_deg, origin="center", use_radians=False)
        return CADPartFactory.normalize_to_origin(rotated)

    @staticmethod
    def verify_placement_sanitizer(
        candidate_poly: Polygon,
        raw_sheet_poly: Polygon,
        already_placed: List[PlacedPartInstance],
        kerf_mm: float,
        eps_area: float = 1e-3,
    ) -> Tuple[bool, str]:
        """Insight Batch 2 Server-Side Sanitizer:

        Independently verifies three physical invariants before accepting any placement:
          1. 100% inside the outer boundary of the sheet.
          2. 0.00 mm2 overlap with any interior cutout hole of the sheet.
          3. 0.00 mm2 overlap (and >= kerf_mm clearance) with all previously placed parts.
        """
        outer_shell = Polygon(raw_sheet_poly.exterior.coords)
        if not outer_shell.buffer(1e-4, quad_segs=8).contains(candidate_poly):
            return False, "ERR_OUTSIDE_SHEET_BOUNDARY"

        # Check overlap against every interior hole of the scrap sheet
        for hole_ring in raw_sheet_poly.interiors:
            hole_poly = Polygon(hole_ring)
            overlap_area = candidate_poly.intersection(hole_poly).area
            if overlap_area > eps_area:
                return False, f"ERR_HOLE_OVERLAP ({overlap_area:.4f} mm2)"
            if kerf_mm > 0.0 and candidate_poly.distance(hole_poly) < (kerf_mm - 0.15):
                return False, "ERR_HOLE_KERF_VIOLATION"

        # Check overlap and kerf clearance against all previously placed parts on this sheet
        for prev in already_placed:
            inter_area = candidate_poly.intersection(prev.polygon).area
            if inter_area > eps_area:
                return False, f"ERR_PART_OVERLAP_WITH_{prev.instance_id}"
            if kerf_mm > 0.0 and candidate_poly.distance(prev.polygon) < (kerf_mm - 0.15):
                return False, f"ERR_KERF_CLEARANCE_WITH_{prev.instance_id}"

        return True, "VERIFIED_SAFE"

    def _find_best_pose_on_sheet(
        self,
        part_spec: CADPartSpec,
        free_space: Union[Polygon, MultiPolygon],
        raw_sheet_poly: Polygon,
        already_placed: List[PlacedPartInstance],
    ) -> Optional[Tuple[Polygon, float, float, float]]:
        """Searches rotations and scans a Bottom-Left (Y ascending, X ascending) grid

        using C++ GEOS prepared containment, followed by a 1mm gravity slide.
        """
        if free_space.is_empty:
            return None

        half_kerf = self.kerf_mm / 2.0
        allowed_angles = [0.0, 180.0] if part_spec.grain_locked else [0.0, 90.0, 180.0, 270.0]

        # Pre-compute rotated part geometries and their expanded half-kerf footprints
        rotated_candidates: List[Tuple[float, Polygon, Polygon, float, float]] = []
        seen_dims = set()
        for angle in allowed_angles:
            rot_poly = self._rotate_and_normalize(part_spec.polygon, angle)
            p_minx, p_miny, p_maxx, p_maxy = rot_poly.bounds
            w_p = round(p_maxx - p_minx, 2)
            h_p = round(p_maxy - p_miny, 2)

            # Skip redundant symmetric rotations (e.g., circle or square at 0 vs 90 deg)
            dim_key = (w_p, h_p, round(rot_poly.area, 1))
            if angle > 0.0 and dim_key in seen_dims and len(part_spec.polygon.interiors) == 0:
                # Keep 90 deg for L-brackets (which have same WxH when equal-legged, so include centroid)
                cx, cy = rot_poly.centroid.x, rot_poly.centroid.y
                dim_key = (w_p, h_p, round(cx, 1), round(cy, 1))
                if dim_key in seen_dims:
                    continue
            seen_dims.add(dim_key)

            footprint = (
                rot_poly.buffer(half_kerf, quad_segs=16)
                if half_kerf > 0.0
                else rot_poly
            )
            rotated_candidates.append((angle, rot_poly, footprint, w_p, h_p))

        prepared_free = prep(free_space)
        f_minx, f_miny, f_maxx, f_maxy = free_space.bounds

        best_choice: Optional[Tuple[float, float, Polygon, float]] = None  # (y, x, poly, angle)

        for angle, rot_poly, footprint, w_p, h_p in rotated_candidates:
            max_search_x = f_maxx - w_p
            max_search_y = f_maxy - h_p
            if max_search_x < f_minx or max_search_y < f_miny:
                continue

            # Generate candidate Y and X grid coordinates
            y_vals = list(
                self._frange(f_miny, max_search_y, self.coarse_step_mm)
            )
            x_vals = list(
                self._frange(f_minx, max_search_x, self.coarse_step_mm)
            )

            found_for_angle = False
            for cy in y_vals:
                # Early exit if we already found a lower Y at another rotation
                if best_choice is not None and cy > best_choice[0] + self.coarse_step_mm:
                    break

                for cx in x_vals:
                    moved_fp = affinity.translate(footprint, xoff=cx, yoff=cy)
                    if prepared_free.contains(moved_fp):
                        # Refine with 1mm Bottom-Left gravity slide
                        rx, ry = self._gravity_slide(
                            footprint, prepared_free, cx, cy, f_minx, f_miny
                        )
                        final_poly = affinity.translate(rot_poly, xoff=rx, yoff=ry)

                        ok, _ = self.verify_placement_sanitizer(
                            final_poly, raw_sheet_poly, already_placed, self.kerf_mm
                        )
                        if ok:
                            score_tuple = (ry, rx)
                            if best_choice is None or score_tuple < (best_choice[0], best_choice[1]):
                                best_choice = (ry, rx, final_poly, angle)
                            found_for_angle = True
                            break
                if found_for_angle:
                    break

        if best_choice is None:
            return None

        best_y, best_x, best_poly, best_angle = best_choice
        return best_poly, round(best_x, 2), round(best_y, 2), best_angle

    def _gravity_slide(
        self,
        footprint: Polygon,
        prepared_free,
        start_x: float,
        start_y: float,
        min_x: float,
        min_y: float,
    ) -> Tuple[float, float]:
        """Slides a valid placement down (-Y) and left (-X) in fine_step_mm increments."""
        curr_x, curr_y = start_x, start_y
        step = self.fine_step_mm

        # Slide down (-Y) until touching boundary
        while curr_y - step >= min_y:
            test_fp = affinity.translate(footprint, xoff=curr_x, yoff=curr_y - step)
            if prepared_free.contains(test_fp):
                curr_y -= step
            else:
                break

        # Slide left (-X) until touching boundary
        while curr_x - step >= min_x:
            test_fp = affinity.translate(footprint, xoff=curr_x - step, yoff=curr_y)
            if prepared_free.contains(test_fp):
                curr_x -= step
            else:
                break

        return curr_x, curr_y

    @staticmethod
    def _frange(start: float, stop: float, step: float):
        curr = start
        while curr <= stop + 1e-5:
            yield curr
            curr += step

    def nest_batch_across_sheets(
        self,
        sheets: List[RemnantRecord],
        part_specs: List[CADPartSpec],
    ) -> BatchNestingResult:
        """Executes multi-sheet batch nesting with:

          - Largest-First sorting (by envelope area descending)
          - Skip-and-Backfill spillover across sheets (Scenario 7)
          - Donut-Hole reuse (Scenario 2)
          - Independent Server-Side Sanitizer check on every placed part
        """
        # Expand quantities into individual queue items and sort Largest-Envelope-First
        expanded_queue: List[Tuple[str, CADPartSpec]] = []
        for spec in part_specs:
            for idx in range(1, spec.quantity + 1):
                inst_id = f"{spec.part_id}_{idx:03d}"
                expanded_queue.append((inst_id, spec))

        expanded_queue.sort(
            key=lambda item: (item[1].envelope_area_mm2, item[1].solid_area_mm2),
            reverse=True,
        )

        total_requested = len(expanded_queue)
        unplaced_queue = list(expanded_queue)
        sheet_outcomes: List[SheetNestingOutcome] = []
        half_kerf = self.kerf_mm / 2.0

        for sheet in sheets:
            if not unplaced_queue:
                break

            # Shrink sheet inward by half_kerf (and expand holes outward by half_kerf)
            free_space = (
                sheet.polygon.buffer(-half_kerf, quad_segs=16)
                if half_kerf > 0.0
                else sheet.polygon
            )
            kerf_safe_poly = free_space

            placed_on_this_sheet: List[PlacedPartInstance] = []
            still_unplaced: List[Tuple[str, CADPartSpec]] = []

            # Cache of (name, env_area, solid_area, grain_locked) that failed to fit
            # on this sheet so we don't re-scan 40 identical circles once sheet is full
            failed_signatures_on_sheet: Set[Tuple] = set()

            for inst_id, spec in unplaced_queue:
                sig = (
                    spec.polygon.wkb,
                    spec.grain_locked,
                )
                if sig in failed_signatures_on_sheet:
                    still_unplaced.append((inst_id, spec))
                    continue

                pose = self._find_best_pose_on_sheet(
                    spec, free_space, sheet.polygon, placed_on_this_sheet
                )
                if pose is None:
                    # Scenario 7 (Skip & Backfill): This large part didn't fit, mark signature as full
                    # for this sheet, push to spillover, and keep trying smaller parts!
                    failed_signatures_on_sheet.add(sig)
                    still_unplaced.append((inst_id, spec))
                else:
                    placed_poly, px, py, pang = pose
                    instance = PlacedPartInstance(
                        instance_id=inst_id,
                        part_id=spec.part_id,
                        name=spec.name,
                        sheet_id=sheet.sheet_id,
                        x_mm=px,
                        y_mm=py,
                        rotation_deg=pang,
                        polygon=placed_poly,
                    )
                    placed_on_this_sheet.append(instance)

                    # Subtract solid part footprint (+ half_kerf) from free_space.
                    # Scenario 2 (Donut-Hole Reuse): Because `placed_poly` is a Polygon with an
                    # interior hole if it's a ring, `.buffer(half_kerf)` only buffers the solid ring wall,
                    # automatically leaving the hollow center inside `free_space` for smaller parts!
                    carved_out = (
                        placed_poly.buffer(half_kerf, quad_segs=16)
                        if half_kerf > 0.0
                        else placed_poly
                    )
                    free_space = free_space.difference(carved_out)

            if placed_on_this_sheet:
                placed_solid_area = sum(p.polygon.area for p in placed_on_this_sheet)
                rem_area = round(
                    max(0.0, sheet.usable_area_mm2 - placed_solid_area), 2
                )
                util_pct = round(
                    (placed_solid_area / max(sheet.usable_area_mm2, 1e-5)) * 100.0,
                    2,
                )
                sheet_outcomes.append(
                    SheetNestingOutcome(
                        sheet_id=sheet.sheet_id,
                        outer_area_mm2=sheet.outer_area_mm2,
                        initial_usable_area_mm2=sheet.usable_area_mm2,
                        remaining_usable_area_mm2=rem_area,
                        utilization_pct=util_pct,
                        placed_parts=placed_on_this_sheet,
                        kerf_safe_zone_polygon=kerf_safe_poly,
                    )
                )

            unplaced_queue = still_unplaced

        total_placed = total_requested - len(unplaced_queue)
        status = (
            "COMPLETE"
            if len(unplaced_queue) == 0
            else ("PARTIAL_SPILLOVER" if total_placed > 0 else "INSUFFICIENT_STOCK")
        )

        return BatchNestingResult(
            status=status,
            total_requested=total_requested,
            total_placed=total_placed,
            sheets_used=len(sheet_outcomes),
            sheet_outcomes=sheet_outcomes,
            unplaced_instances=[item[0] for item in unplaced_queue],
            sanitizer_verified=True,
        )


# Compatibility for earlier Python callers; the algorithm is a grid search.
HoleAwareNFPNester = HoleAwareNester
